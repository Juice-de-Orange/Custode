"""Der Purge nach der Karenz — und die Rechte, ohne die er jede Nacht stumm stürbe (11-S1d).

Die erste Hälfte dieser Datei ist der Test, den der Retention-Reaper nicht hatte: **Postgres prüft
Tabellenrechte beim Planen, nicht beim Treffer.** Ein fehlendes DELETE lässt die Anweisung
scheitern, auch wenn es gar nichts zu löschen gäbe — und ein Job, der nur bei Wirkung loggt, sieht
im Fehlerfall aus wie einer, der nichts zu tun fand (BUGLOG 2026-07-31). Die Bestandsaufnahme vor
Migration 0072 ergab: von 14 Purge-Tabellen erlaubten **vier** dem Wartungs-Rollen-Konto ein
DELETE, und **vier** hatten überhaupt keine Policy.

Die zweite Hälfte ist der Ablauf selbst, und dort gilt die andere Regel dieser Codebasis: **ein
Test über einen Entzug muss erst beweisen, dass es etwas zu entziehen gab.** Jeder Test hier zählt
vorher.

Ohne Docker übersprungen.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from app.deletion_policy import ANONYMISE_USER, PURGED_TABLES, RULES, Disposal
from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = {k: os.environ.get(k) for k in ("CUSTODE_DATABASE_URL", "CUSTODE_DATABASE_URL_MAINT")}
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
    try:
        yield
    finally:
        for eng in (engine_mod._engine, engine_mod._maint_engine):
            if eng is not None:
                await eng.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


async def _su(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


# --- Die Rechte: der Test, den der Reaper nicht hatte ---------------------------------------------


async def test_maint_may_select_and_delete_on_every_purged_table(pg: PgDatabase) -> None:
    """Ohne diesen Test ist ``PURGED_TABLES`` eine Behauptung über die Datenbank."""
    conn = await _su(pg)
    try:
        missing: list[str] = []
        for table in PURGED_TABLES:
            for privilege in ("SELECT", "DELETE"):
                granted = await conn.fetchval(
                    "SELECT has_table_privilege('custode_maint', $1, $2);", table, privilege
                )
                if not granted:
                    missing.append(f"{table}:{privilege}")
    finally:
        await conn.close()
    assert missing == [], (
        "Postgres prüft Rechte beim PLANEN — der Purge stürbe hier jede Nacht mit "
        "permission denied, auch wenn gar kein Konto fällig wäre."
    )


async def test_maint_may_update_users(pg: PgDatabase) -> None:
    """Die Anonymisierung ist ein UPDATE auf ``users``.

    Vor Migration 0072 hatte ``custode_maint`` genau das nicht."""
    conn = await _su(pg)
    try:
        assert await conn.fetchval(
            "SELECT has_table_privilege('custode_maint', 'users', 'UPDATE');"
        )
    finally:
        await conn.close()


async def test_every_purged_table_has_the_maint_policy(pg: PgDatabase) -> None:
    """Rechte ohne Policy reichen nicht: mit ``FORCE ROW LEVEL SECURITY`` sieht der Job sonst
    schlicht keine Zeile — und löscht fehlerfrei nichts. Das ist die leisere Hälfte derselben
    Falle."""
    conn = await _su(pg)
    try:
        without = []
        for table in PURGED_TABLES:
            has_policy = await conn.fetchval(
                "SELECT EXISTS (SELECT 1 FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid "
                "WHERE c.relname = $1 AND p.polname = 'maint_all');",
                table,
            )
            if not has_policy:
                without.append(table)
    finally:
        await conn.close()
    assert without == []


# --- Der Ablauf ----------------------------------------------------------------------------------


async def _seed(pg: PgDatabase) -> dict[str, uuid.UUID]:
    """Ein Haushalt, zwei Personen, und für die zu löschende Person Zeilen in beiden Lagern —
    in solchen, die gehen müssen, und in solchen, die bleiben müssen."""
    ids = {
        "household": uuid.uuid4(),
        "gone": uuid.uuid4(),
        "stays": uuid.uuid4(),
        "list": uuid.uuid4(),
        "letter": uuid.uuid4(),
    }
    conn = await _su(pg)
    try:
        await conn.execute(
            "TRUNCATE households, users, memberships, auth_sessions, auth_login_events, "
            "captures, calendar_feeds, letters, letter_reads, shopping_lists, shopping_items, "
            "feedback CASCADE;"
        )
        await conn.execute("INSERT INTO households (id,name) VALUES ($1,'WG');", ids["household"])
        for key, mail in (("gone", "gone@example.org"), ("stays", "stays@example.org")):
            await conn.execute(
                "INSERT INTO users (id,email,display_name,password_hash,locale) "
                "VALUES ($1,$2,$3,'x','de');",
                ids[key],
                mail,
                key,
            )
            await conn.execute(
                "INSERT INTO memberships (household_id,user_id,role) VALUES ($1,$2,'admin');",
                ids["household"],
                ids[key],
            )
        # --- muss gehen -------------------------------------------------------------------------
        await conn.execute(
            "INSERT INTO auth_sessions (user_id,family_id,refresh_hash,expires_at) "
            "VALUES ($1,$2,$3, now() + interval '30 days');",
            ids["gone"],
            uuid.uuid4(),
            uuid.uuid4().hex,
        )
        await conn.execute(
            "INSERT INTO auth_login_events (user_id,success) VALUES ($1,true);", ids["gone"]
        )
        await conn.execute(
            "INSERT INTO captures (household_id,member_id,raw_text) VALUES ($1,$2,'Notiz');",
            ids["household"],
            ids["gone"],
        )
        await conn.execute(
            "INSERT INTO calendar_feeds (household_id,member_id,token) VALUES ($1,$2,$3);",
            ids["household"],
            ids["gone"],
            uuid.uuid4().hex,
        )
        await conn.execute(
            "INSERT INTO letters (id,household_id,from_id,to_ids,subject,body_md) "
            "VALUES ($1,$2,$3,ARRAY[$4]::uuid[],'Betreff','Text');",
            ids["letter"],
            ids["household"],
            ids["stays"],
            ids["gone"],
        )
        await conn.execute(
            "INSERT INTO letter_reads (household_id,letter_id,user_id) VALUES ($1,$2,$3);",
            ids["household"],
            ids["letter"],
            ids["gone"],
        )
        # --- muss bleiben: geteilter Bestand -----------------------------------------------------
        await conn.execute(
            "INSERT INTO shopping_lists (id,household_id,name) VALUES ($1,$2,'Wocheneinkauf');",
            ids["list"],
            ids["household"],
        )
        await conn.execute(
            "INSERT INTO shopping_items (household_id,list_id,label,created_by) "
            "VALUES ($1,$2,'Milch',$3);",
            ids["household"],
            ids["list"],
            ids["gone"],
        )
        # Karenz abgelaufen.
        await conn.execute(
            "UPDATE users SET deleted_at = $2 WHERE id = $1;",
            ids["gone"],
            datetime.now(UTC) - timedelta(days=40),
        )
        await conn.execute(
            "UPDATE memberships SET deleted_at = now() WHERE user_id = $1;", ids["gone"]
        )
    finally:
        await conn.close()
    return ids


async def test_the_purge_removes_everything_that_is_about_the_person(
    pg: PgDatabase, db: None
) -> None:
    """Erst zählen, dann räumen, dann nachzählen — und zwar über **alle** Regeln, nicht nur die
    gesäten. Eine vergessene DELETE-Anweisung fiele sonst genau dort durch, wo nichts stand."""
    from app.account_purge import purge_due_accounts

    ids = await _seed(pg)

    conn = await _su(pg)
    try:
        before = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id=$1;", ids["gone"]
        ) + await conn.fetchval("SELECT count(*) FROM captures WHERE member_id=$1;", ids["gone"])
    finally:
        await conn.close()
    assert before == 2, "Vorbedingung: es gibt etwas zu löschen"

    run = await purge_due_accounts(retention_days=30)
    assert run.failed == {}, "kein Konto darf an fehlenden Rechten scheitern"
    assert len(run.purged) == 1

    conn = await _su(pg)
    try:
        leftovers: list[str] = []
        for rule in RULES:
            if rule.disposal is not Disposal.delete:
                continue
            count = await conn.fetchval(
                f"SELECT count(*) FROM {rule.table} WHERE {rule.column} = $1;",  # noqa: S608
                ids["gone"],
            )
            if count:
                leftovers.append(f"{rule.table}.{rule.column}={count}")
    finally:
        await conn.close()
    assert leftovers == [], "diese Zeilen sind ÜBER die Person und hätten gehen müssen"


async def test_the_shared_contribution_stays_and_points_at_the_anonymous_row(
    pg: PgDatabase, db: None
) -> None:
    """KONZEPT §5.1: Beiträge bleiben, der Name wird pseudonym. Das ist der Grund, warum die
    ``users``-Zeile überhaupt stehen bleibt — ohne sie zeigte dieser Verweis ins Leere."""
    from app.account_purge import purge_due_accounts

    ids = await _seed(pg)

    conn = await _su(pg)
    try:
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM shopping_items WHERE created_by=$1;", ids["gone"]
            )
            == 1
        ), "Vorbedingung: der Beitrag existiert"
    finally:
        await conn.close()

    await purge_due_accounts(retention_days=30)

    conn = await _su(pg)
    try:
        still_there = await conn.fetchval(
            "SELECT count(*) FROM shopping_items WHERE created_by=$1;", ids["gone"]
        )
        row = await conn.fetchrow(
            "SELECT email, display_name, password_hash, purged_at FROM users WHERE id=$1;",
            ids["gone"],
        )
    finally:
        await conn.close()

    assert still_there == 1, "der gemeinsame Bestand darf nicht verschwinden"
    assert row is not None, "die users-Zeile bleibt — sonst hinge der Verweis oben in der Luft"
    assert row["email"] is None
    assert row["password_hash"] is None
    assert row["display_name"] == "", (
        "geleert, NICHT auf einen Ersatznamen gesetzt: ein deutscher Anzeigetext in der Datenbank "
        "bräche die i18n-Regel und wäre zum Löschzeitpunkt eingefroren"
    )
    assert row["purged_at"] is not None


async def test_a_person_still_inside_the_grace_period_is_untouched(
    pg: PgDatabase, db: None
) -> None:
    """Die Gegenprobe zur Frist. Ohne sie bestünde der Test oben auch bei einem Purge, der
    wahllos alles nimmt."""
    from app.account_purge import find_due_accounts, purge_due_accounts

    ids = await _seed(pg)
    conn = await _su(pg)
    try:
        await conn.execute(
            "UPDATE users SET deleted_at = now() - interval '3 days' WHERE id=$1;", ids["gone"]
        )
    finally:
        await conn.close()

    assert await find_due_accounts(retention_days=30) == []
    run = await purge_due_accounts(retention_days=30)
    assert run.purged == []

    conn = await _su(pg)
    try:
        assert (
            await conn.fetchval("SELECT count(*) FROM captures WHERE member_id=$1;", ids["gone"])
            == 1
        )
        assert await conn.fetchval("SELECT email FROM users WHERE id=$1;", ids["gone"]) is not None
    finally:
        await conn.close()


async def test_the_other_person_is_not_touched(pg: PgDatabase, db: None) -> None:
    """Ein Purge, der einen Haushalt leerräumt statt eine Person, bestünde jeden Test oben."""
    from app.account_purge import purge_due_accounts

    ids = await _seed(pg)
    await purge_due_accounts(retention_days=30)

    conn = await _su(pg)
    try:
        row = await conn.fetchrow("SELECT email, purged_at FROM users WHERE id=$1;", ids["stays"])
        letters = await conn.fetchval(
            "SELECT count(*) FROM letters WHERE from_id=$1;", ids["stays"]
        )
    finally:
        await conn.close()
    assert row is not None and row["email"] == "stays@example.org"
    assert row["purged_at"] is None
    assert letters == 1


async def test_a_second_run_finds_nothing_and_changes_nothing(pg: PgDatabase, db: None) -> None:
    """``purged_at`` ist genau dafür da. Ohne die zweite Spalte sähe jeder Lauf dieselbe Zeile
    wieder als fällig — und schriebe jede Nacht ein neues Datum in ein längst leeres Konto."""
    from app.account_purge import purge_due_accounts

    await _seed(pg)
    first = await purge_due_accounts(retention_days=30)
    assert len(first.purged) == 1

    second = await purge_due_accounts(retention_days=30)
    assert second.purged == []
    assert second.failed == {}


async def test_every_anonymised_column_is_actually_cleared(pg: PgDatabase, db: None) -> None:
    """``ANONYMISE_USER`` behauptet, jede genannte Spalte auszuräumen. Der Test prüft die
    Behauptung an der Zeile, nicht an der Liste."""
    from app.account_purge import purge_due_accounts

    ids = await _seed(pg)
    await purge_due_accounts(retention_days=30)

    columns = ", ".join(ANONYMISE_USER)
    conn = await _su(pg)
    try:
        row = await conn.fetchrow(
            f"SELECT {columns} FROM users WHERE id=$1;",  # noqa: S608
            ids["gone"],
        )
    finally:
        await conn.close()
    assert row is not None
    for column, expected in ANONYMISE_USER.items():
        assert row[column] == expected or (expected == {} and row[column] in ("{}", {})), (
            f"{column} wurde nicht auf den klassifizierten Wert gesetzt"
        )


# --- Die Gegenprobe, die beide Seiten aneinander hält ---------------------------------------------


async def test_an_export_after_the_purge_carries_no_personal_row(pg: PgDatabase, db: None) -> None:
    """Der Schlusstest des ganzen Strangs — und der einzige, der Klassifizierung und Purge
    **gegeneinander** hält statt jede für sich.

    Beide Listen sind von Hand gepflegt: ``export_policy`` sagt, welche Zeilen einer Person
    gehören, ``deletion_policy`` sagt, welche beim Löschen gehen. Prüfte man sie nur einzeln, wäre
    eine Tabelle, die in **beiden** vergessen wurde, unauffindbar — sie erschiene weder im Export
    noch im Purge, und beide Testreihen blieben grün.

    Hier läuft der Export der gelöschten Person **nach** dem Purge auf ihrer eigenen Session. Was
    dann noch mit ihrem Namen herauskommt, hat der Purge übersehen. Der Test müsste zweimal
    denselben Fehler machen, um durchzugehen.
    """
    from app.account_purge import purge_due_accounts
    from app.export_policy import POLICY
    from app.kernel.export import ExportScope, collect_export
    from app.kernel.tenancy.session import scoped_session

    ids = await _seed(pg)

    async with scoped_session(household_id=ids["household"], user_id=ids["gone"]) as session:
        before = await collect_export(
            session, policy=POLICY, scope=ExportScope.PERSONAL, subject_id=ids["gone"]
        )
    filled_before = {name: len(rows) for name, rows in before.sections.items() if rows}
    assert filled_before, "Vorbedingung: der Export dieser Person ist NICHT leer"

    await purge_due_accounts(retention_days=30)

    async with scoped_session(household_id=ids["household"], user_id=ids["gone"]) as session:
        after = await collect_export(
            session, policy=POLICY, scope=ExportScope.PERSONAL, subject_id=ids["gone"]
        )

    # Was noch kommt, muss **klassifiziert** sein — und zwar als `keep`. Drei Fälle:
    #
    #   `delete`-Regel  → der Purge hat sie übersehen. Fehler.
    #   gar keine Regel → BEIDE Listen haben die Tabelle vergessen. Der eigentliche Fund dieses
    #                     Tests: er ist der einzige Ort, an dem das auffällt.
    #   `keep`-Regel    → in Ordnung. Der Export rechnet die Zeile der Person zu (Art. 15: du
    #                     bekommst eine Kopie dessen, was du beigetragen hast), die Löschung lässt
    #                     sie beim Haushalt (KONZEPT §5.1). Beides ist zugleich wahr, und der
    #                     Verweis zeigt danach auf eine leere `users`-Zeile — das IST die
    #                     Pseudonymisierung, nicht ihr Gegenteil.
    keep_tables = {rule.table for rule in RULES if rule.disposal is Disposal.keep}
    delete_tables = {rule.table for rule in RULES if rule.disposal is Disposal.delete}
    remaining = {name for name, rows in after.sections.items() if rows} - {"users"}

    not_deleted = sorted(remaining & delete_tables)
    assert not_deleted == [], "der Purge hat diese Tabellen übersehen"

    unclassified = sorted(remaining - keep_tables)
    assert unclassified == [], (
        "Diese Tabellen ordnet der Export der Person zu, und die Löschklassifizierung kennt sie "
        "gar nicht. Beide Listen sind von Hand gepflegt — eine Tabelle, die in BEIDEN fehlt, "
        "fällt nur hier auf."
    )

    # Und die Zeile, die bewusst stehen bleibt, darf nichts mehr über die Person sagen.
    user_rows = after.sections.get("users") or []
    assert len(user_rows) == 1
    assert user_rows[0]["email"] is None
    assert user_rows[0]["display_name"] == ""
