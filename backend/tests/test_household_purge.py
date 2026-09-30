"""Das endgültige Ausräumen eines aufgelösten Haushalts (11-S1f, Art. 17, ADR-0086).

Vier Gates, und jedes hält gegen die **echte** Datenbank statt gegen eine Liste:

1. **Vollständigkeit.** Jede Tabelle mit ``household_id`` im echten Schema ist eingeordnet. Nicht
   über ``Base.metadata`` — das ORM ist nicht das Schema, und genau dort saßen beim Export
   ``tenancy_probe`` und ``guides.search_tsv`` (ADR-0083).
2. **Rechte, vorweg.** Postgres prüft Tabellenrechte beim **Planen**, nicht beim Treffer: ein
   fehlendes DELETE tötet den Lauf, auch wenn nichts zu löschen wäre. Genau daran ist der
   Retention-Reaper drei Wochen lang jede Nacht gestorben (BUGLOG 2026-07-31), und beim Konto-Purge
   fand dieselbe Prüfung vorweg 4 von 14 Tabellen ohne Recht.
3. **Reihenfolge.** Kinder vor Eltern — und die **umgekehrte** Reihenfolge muss an den
   ``NO ACTION``-Constraints scheitern. Ohne diese Gegenprobe beweist ein grüner Lauf nur, dass
   zufällig nichts kollidierte.
4. **Wirkung.** Nach dem Lauf trägt **keine** Tabelle mehr eine Zeile dieses Haushalts, und die
   ``households``-Zeile ist weg. Geprüft wird generisch über alle 41 Tabellen; die Seeds sind der
   Beleg, dass die Prüfung nicht leer läuft.

Dazu die Gegenproben, ohne die nichts davon etwas beweist: ein **zweiter, lebender** Haushalt bleibt
unberührt, ein noch nicht fälliger bleibt stehen, und die Art.-9-Daten eines **zweiten** Mitglieds
fallen mit — unter einer einzigen Identität blieben sie liegen, ohne Fehler (ADR-0081).

Ohne Docker übersprungen.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

import app.kernel.db.engine as engine_mod
from app.household_deletion_policy import KEEP_REASONS, POLICY
from app.household_purge import find_due_households, purge_due_households, purge_household
from app.kernel.deletion.household import (
    UnclassifiedTableError,
    discover_household_tables,
    order_children_first,
    plan_purge,
)
from app.kernel.tenancy.session import maint_session, scoped_session
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


# --------------------------------------------------------------------------------- Seed


async def _seed_household(conn: asyncpg.Connection, *, dissolved_days_ago: int | None) -> dict:
    """Ein Haushalt mit zwei Mitgliedern und Zeilen in jeder reihenfolgekritischen Kette.

    Getroffen sind alle vier ``NO ACTION``-Ketten (Raum→Vorlage→Instanz, Rezept→Zutat,
    Liste→Posten, Belohnung→Einlösung) und **beide** mitglieds-gescopten Tabellen für **zwei**
    Mitglieder — sonst bliebe der Art.-9-Befund aus ADR-0085 ungeprüft.
    """
    ids = {
        "household": uuid.uuid4(),
        "a": uuid.uuid4(),
        "b": uuid.uuid4(),
        "room": uuid.uuid4(),
        "template": uuid.uuid4(),
        "recipe": uuid.uuid4(),
        "list": uuid.uuid4(),
        "reward": uuid.uuid4(),
    }
    hh = ids["household"]
    deleted = (
        None if dissolved_days_ago is None else f"now() - interval '{int(dissolved_days_ago)} days'"
    )
    await conn.execute(
        f"INSERT INTO households (id, name, deleted_at) VALUES ($1, $2, {deleted or 'NULL'});",  # noqa: S608
        hh,
        f"H-{str(hh)[:8]}",
    )
    for key in ("a", "b"):
        await conn.execute(
            "INSERT INTO users (id, email, display_name) VALUES ($1,$2,$3);",
            ids[key],
            f"{key}-{uuid.uuid4().hex[:10]}@example.org",
            key,
        )
        await conn.execute(
            "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,'member');",
            hh,
            ids[key],
        )
    # Ketten mit NO ACTION — Elternteil zuerst einfuegen, Kind danach.
    await conn.execute(
        "INSERT INTO rooms (id, household_id, name, decay_days) VALUES ($1,$2,'Kueche',7);",
        ids["room"],
        hh,
    )
    await conn.execute(
        "INSERT INTO task_templates (id, household_id, title, room_id) "
        "VALUES ($1,$2,'Wischen',$3);",
        ids["template"],
        hh,
        ids["room"],
    )
    await conn.execute(
        "INSERT INTO task_instances (household_id, template_id, title) VALUES ($1,$2,'Wischen');",
        hh,
        ids["template"],
    )
    await conn.execute(
        "INSERT INTO recipes (id, household_id, title) VALUES ($1,$2,'Suppe');", ids["recipe"], hh
    )
    await conn.execute(
        "INSERT INTO recipe_ingredients (household_id, recipe_id, raw_text) "
        "VALUES ($1,$2,'1 Zwiebel');",
        hh,
        ids["recipe"],
    )
    await conn.execute(
        "INSERT INTO shopping_lists (id, household_id, name) VALUES ($1,$2,'Wocheneinkauf');",
        ids["list"],
        hh,
    )
    await conn.execute(
        "INSERT INTO shopping_items (household_id, list_id, label) VALUES ($1,$2,'Milch');",
        hh,
        ids["list"],
    )
    await conn.execute(
        "INSERT INTO rewards (id, household_id, title, cost) VALUES ($1,$2,'Kinoabend',50);",
        ids["reward"],
        hh,
    )
    await conn.execute(
        "INSERT INTO redemptions (household_id, reward_id, member_id, title, cost) "
        "VALUES ($1,$2,$3,'Kinoabend',50);",
        hh,
        ids["reward"],
        ids["a"],
    )
    # Ökonomie + Inhalt
    await conn.execute(
        "INSERT INTO points_ledger (household_id, from_account, to_account, amount, ref_type) "
        "VALUES ($1,'household','member','25','task');",
        hh,
    )
    await conn.execute(
        "INSERT INTO notes (household_id, author_id, title) VALUES ($1,$2,'Einkaufsnotiz');",
        hh,
        ids["a"],
    )
    # Art. 9 — fuer BEIDE Mitglieder. Der Kern der Mitglieds-Gegenprobe.
    for key in ("a", "b"):
        await conn.execute(
            "INSERT INTO wearable_connections (household_id, member_id, provider, tokens_enc) "
            "VALUES ($1,$2,'oura','v1:token');",
            hh,
            ids[key],
        )
        await conn.execute(
            "INSERT INTO wearable_daily (household_id, member_id, provider, day, sleep_score) "
            "VALUES ($1,$2,'oura',CURRENT_DATE,70);",
            hh,
            ids[key],
        )
    # Eine Tabelle, die ausdruecklich BLEIBT.
    await conn.execute(
        "INSERT INTO consents (household_id, subject_user_id, type, action, granted_by) "
        "VALUES ($1,$2,'wearable_sleep','grant',$2);",
        hh,
        ids["a"],
    )
    return ids


async def _rows_for(conn: asyncpg.Connection, household_id: uuid.UUID) -> dict[str, int]:
    """Wie viele Zeilen jede haushaltsgebundene Tabelle für diesen Haushalt trägt (Superuser)."""
    tables = [
        r["t"]
        for r in await conn.fetch(
            "SELECT c.relname AS t FROM pg_attribute a "
            "JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE a.attname='household_id' AND NOT a.attisdropped AND n.nspname='public' "
            "AND c.relkind IN ('r','p') ORDER BY 1;"
        )
    ]
    counts: dict[str, int] = {}
    for t in tables:
        n = await conn.fetchval(
            f"SELECT count(*) FROM {t} WHERE household_id = $1;",  # noqa: S608
            household_id,
        )
        if n:
            counts[t] = int(n)
    return counts


# ------------------------------------------------------------------- Gate 1: Vollständigkeit


async def test_every_household_table_in_the_real_schema_is_classified(db: None) -> None:
    """Das ORM ist nicht das Schema — gefragt wird der Katalog."""
    async with maint_session() as session:
        discovered = await discover_household_tables(session)
    assert len(discovered) >= 41, discovered
    unknown = sorted(set(discovered) - (POLICY.delete_tables | POLICY.keep_tables))
    assert unknown == [], f"nicht eingeordnet: {unknown}"
    # Rueckrichtung: keine Geistertabelle in der Klassifizierung.
    ghosts = sorted((POLICY.delete_tables | POLICY.keep_tables) - set(discovered))
    assert ghosts == [], f"eingeordnet, existiert aber nicht: {ghosts}"


async def test_the_plan_refuses_to_run_when_a_table_is_unclassified(db: None) -> None:
    """Geschlossen ausfallen: raten waere in beide Richtungen falsch."""
    from app.kernel.deletion.household import HouseholdPurgeSpec

    crippled = HouseholdPurgeSpec(
        delete_tables=POLICY.delete_tables - {"notes"}, keep_tables=POLICY.keep_tables
    )
    async with maint_session() as session:
        with pytest.raises(UnclassifiedTableError, match="notes"):
            await plan_purge(session, spec=crippled)


async def test_keep_tables_carry_a_substantial_reason(db: None) -> None:
    """Eine Tabelle zu behalten ist eine Entscheidung; sie braucht mehr als ein Wort."""
    assert set(KEEP_REASONS) == set(POLICY.keep_tables)
    for table, reason in KEEP_REASONS.items():
        assert len(reason) > 60, f"{table}: Begruendung zu duenn"


# --------------------------------------------------------------------------- Gate 2: Rechte


async def test_the_app_role_may_delete_every_table_it_is_asked_to(db: None, pg: PgDatabase) -> None:
    """Rechte vorweg — Postgres prüft beim Planen, nicht beim Treffer.

    Ein fehlendes DELETE oder eine Policy, die es nicht abdeckt, tötet den Lauf, auch wenn nichts
    zu löschen wäre. Genau daran ist der Retention-Reaper jede Nacht gestorben.
    """
    async with maint_session() as session:
        plan = await plan_purge(session, spec=POLICY)
    probe = uuid.uuid4()
    failures: dict[str, str] = {}
    for table in [*plan, "households"]:
        try:
            async with scoped_session(household_id=probe, user_id=probe) as session:
                from sqlalchemy import text as _text

                await session.execute(_text(f"DELETE FROM {table}"))  # noqa: S608
        except Exception as exc:  # Diagnose sammeln statt beim ersten abbrechen
            failures[table] = (
                getattr(getattr(exc, "orig", None), "sqlstate", None) or type(exc).__name__
            )
    assert failures == {}, f"custode_app darf hier nicht loeschen: {failures}"


async def test_the_kept_tables_are_locked_for_the_app_role(db: None) -> None:
    """Die Einordnung „behalten" ist nicht nur eine Zusage — die Datenbank hält sie.

    Ohne diesen Test wäre ``keep`` eine Absicht, die ein späterer Grant stillschweigend aufhebt.
    """
    probe = uuid.uuid4()
    from sqlalchemy import text as _text

    for table in sorted(POLICY.keep_tables):
        with pytest.raises(Exception) as excinfo:  # der SQLSTATE ist die Aussage
            async with scoped_session(household_id=probe, user_id=probe) as session:
                await session.execute(_text(f"DELETE FROM {table}"))  # noqa: S608
        sqlstate = getattr(getattr(excinfo.value, "orig", None), "sqlstate", None)
        assert sqlstate == "42501", f"{table}: erwartet 42501, bekam {sqlstate}"


# ----------------------------------------------------------------------- Gate 3: Reihenfolge


def test_children_are_ordered_before_their_parents() -> None:
    edges = [("shopping_items", "shopping_lists"), ("task_instances", "task_templates")]
    order = order_children_first(
        ["shopping_lists", "shopping_items", "task_templates", "task_instances"], edges
    )
    assert order.index("shopping_items") < order.index("shopping_lists")
    assert order.index("task_instances") < order.index("task_templates")


def test_the_order_is_deterministic() -> None:
    """Eine laufzeitabhaengige Reihenfolge macht jeden Fehlschlag unreproduzierbar."""
    tables = ["rooms", "task_templates", "task_instances", "notes", "recipes"]
    edges = [("task_templates", "rooms"), ("task_instances", "task_templates")]
    assert order_children_first(tables, edges) == order_children_first(
        list(reversed(tables)), edges
    )


async def test_the_real_plan_puts_the_no_action_chains_in_the_right_order(db: None) -> None:
    async with maint_session() as session:
        plan = await plan_purge(session, spec=POLICY)
    for child, parent in (
        ("task_instances", "task_templates"),
        ("task_templates", "rooms"),
        ("recipe_ingredients", "recipes"),
        ("shopping_items", "shopping_lists"),
        ("redemptions", "rewards"),
    ):
        assert plan.index(child) < plan.index(parent), f"{child} muss vor {parent} fallen"


async def test_the_reversed_order_really_fails(db: None, pg: PgDatabase) -> None:
    """Ohne diese Gegenprobe beweist der gruene Lauf nur, dass zufaellig nichts kollidierte."""
    conn = await _su(pg)
    try:
        ids = await _seed_household(conn, dissolved_days_ago=40)
    finally:
        await conn.close()

    async with maint_session() as session:
        plan = await plan_purge(session, spec=POLICY)

    from sqlalchemy import text as _text

    with pytest.raises(Exception) as excinfo:  # der SQLSTATE ist die Aussage
        async with scoped_session(household_id=ids["household"], user_id=ids["a"]) as session:
            for table in reversed(plan):
                await session.execute(_text(f"DELETE FROM {table}"))  # noqa: S608
    sqlstate = getattr(getattr(excinfo.value, "orig", None), "sqlstate", None)
    assert sqlstate == "23503", f"erwartet Fremdschluessel-Verletzung, bekam {sqlstate}"


# --------------------------------------------------------------------------- Gate 4: Wirkung


async def test_a_due_household_is_emptied_completely(db: None, pg: PgDatabase) -> None:
    conn = await _su(pg)
    try:
        ids = await _seed_household(conn, dissolved_days_ago=40)
        before = await _rows_for(conn, ids["household"])
    finally:
        await conn.close()

    # Vorher: es gibt wirklich etwas zu loeschen — sonst prueft das Nachher nichts.
    assert len(before) >= 12, before
    assert before.get("wearable_daily") == 2, "beide Mitglieder muessen Art.-9-Zeilen haben"

    result = await purge_household(ids["household"])
    assert result.household_row_removed is True

    conn = await _su(pg)
    try:
        after = await _rows_for(conn, ids["household"])
        household_rows = await conn.fetchval(
            "SELECT count(*) FROM households WHERE id = $1;", ids["household"]
        )
    finally:
        await conn.close()

    # Nachher: nur die ausdruecklich behaltenen Tabellen tragen noch Zeilen.
    assert set(after) <= POLICY.keep_tables, f"nicht ausgeraeumt: {sorted(set(after))}"
    assert after.get("consents") == 1, "der Einwilligungs-Nachweis muss bleiben"
    assert household_rows == 0


async def test_the_art9_rows_of_every_member_fall_not_just_the_first(
    db: None, pg: PgDatabase
) -> None:
    """Der Befund aus ADR-0085 in Testform.

    Die mitglieds-gescopte Policy laesst unter einer einzigen Identitaet nur die eigenen Zeilen
    fallen — und meldet dabei **erfolgreich** „0 Zeilen" fuer die anderen. Ohne diesen Test saehe
    ein Lauf, der die Art.-9-Daten des zweiten Mitglieds liegen laesst, genauso gruen aus.
    """
    conn = await _su(pg)
    try:
        ids = await _seed_household(conn, dissolved_days_ago=40)
        both = await conn.fetchval(
            "SELECT count(DISTINCT member_id) FROM wearable_daily WHERE household_id = $1;",
            ids["household"],
        )
    finally:
        await conn.close()
    assert both == 2

    await purge_household(ids["household"])

    conn = await _su(pg)
    try:
        left = await conn.fetchval(
            "SELECT count(*) FROM wearable_daily WHERE household_id = $1;", ids["household"]
        )
        left_conn = await conn.fetchval(
            "SELECT count(*) FROM wearable_connections WHERE household_id = $1;", ids["household"]
        )
    finally:
        await conn.close()
    assert left == 0
    assert left_conn == 0


async def test_a_living_household_is_untouched(db: None, pg: PgDatabase) -> None:
    """Die Gegenprobe, ohne die alles obige nur beweist, dass irgendetwas kaputtgeht."""
    conn = await _su(pg)
    try:
        doomed = await _seed_household(conn, dissolved_days_ago=40)
        alive = await _seed_household(conn, dissolved_days_ago=None)
        alive_before = await _rows_for(conn, alive["household"])
    finally:
        await conn.close()
    assert len(alive_before) >= 12

    run = await purge_due_households(retention_days=30)
    assert run.failed == {}, run.failed
    # Auf Mengen prüfen, nicht auf Gleichheit: die Datenbank ist modulweit geteilt, und ein
    # Vorgänger-Test kann einen weiteren fälligen Haushalt hinterlassen haben. Die Aussage ist
    # „der fällige fällt, der lebende nicht" — nicht „genau einer fiel".
    purged = {r.household_id for r in run.purged}
    assert doomed["household"] in purged
    assert alive["household"] not in purged

    conn = await _su(pg)
    try:
        alive_after = await _rows_for(conn, alive["household"])
        alive_row = await conn.fetchval(
            "SELECT count(*) FROM households WHERE id = $1;", alive["household"]
        )
    finally:
        await conn.close()
    assert alive_after == alive_before
    assert alive_row == 1


async def test_a_household_still_within_the_grace_period_stays(db: None, pg: PgDatabase) -> None:
    conn = await _su(pg)
    try:
        fresh = await _seed_household(conn, dissolved_days_ago=3)
    finally:
        await conn.close()

    assert fresh["household"] not in await find_due_households(retention_days=30)
    run = await purge_due_households(retention_days=30)
    assert fresh["household"] not in {r.household_id for r in run.purged}

    conn = await _su(pg)
    try:
        still = await conn.fetchval(
            "SELECT count(*) FROM households WHERE id = $1;", fresh["household"]
        )
    finally:
        await conn.close()
    assert still == 1


async def test_the_purge_is_idempotent(db: None, pg: PgDatabase) -> None:
    conn = await _su(pg)
    try:
        ids = await _seed_household(conn, dissolved_days_ago=40)
    finally:
        await conn.close()

    first = await purge_household(ids["household"])
    assert first.total > 0
    second = await purge_household(ids["household"])
    assert second.total == 0
    assert second.household_row_removed is False
