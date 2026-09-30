"""Selbst gehen können, nicht nur gegangen werden (KONZEPT §5.1, Slice A).

Bis hierher gab es genau einen Weg aus einem Haushalt heraus: ein Admin entfernt jemanden
(`DELETE /v1/household/members/{id}`, `AdminPrincipal`). Wer selbst gehen wollte, musste darum
bitten — und KONZEPT §5.1 verspricht den Austritt als Recht der Person, nicht als Gefallen.

Der interessante Teil sind die **Abweisungsgründe**, nicht der Erfolgsfall. Sie sind fast, aber
nicht ganz dieselben wie bei der Kontolöschung, und der Unterschied ist Absicht:

- ``last_admin`` / ``only_children`` — identisch, deshalb teilen sich beide Pfade seit diesem Slice
  die reine Funktion ``exit_blocker_reason``. Zwei Fassungen liefen unweigerlich auseinander.
- ``sole_member`` — **nur** beim Austritt. Wer allein in einem Haushalt ist, verlässt ihn nicht, er
  löst ihn auf; zurückbliebe sonst ein Haushalt ohne jedes Mitglied, in den niemand mehr
  hineinkommt (Einladungen brauchen einen Admin). Die Kontolöschung lässt genau diesen Fall zu,
  weil es dort kein „stattdessen" gibt. ``test_the_two_paths_disagree_about_the_solo_household``
  hält den Unterschied fest, damit ihn niemand später „vereinheitlicht".

Jeder Test beweist erst das Vorher. Ohne Docker übersprungen.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase

PASSWORD = "korrekt-pferd-batterie-klammer"


@pytest.fixture
async def db(pg: PgDatabase, redis_db: None) -> AsyncIterator[None]:
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


async def _seed(pg: PgDatabase, roles: dict[str, str]) -> dict[str, uuid.UUID]:
    """Ein Haushalt mit genau den angegebenen Rollen (Schlüssel → Rolle)."""
    from app.kernel.auth.passwords import hash_password

    ids: dict[str, uuid.UUID] = {"household": uuid.uuid4()}
    conn = await _su(pg)
    try:
        await conn.execute(
            "TRUNCATE households, users, memberships, auth_sessions, events_outbox CASCADE;"
        )
        await conn.execute("INSERT INTO households (id,name) VALUES ($1,'WG');", ids["household"])
        for key, role in roles.items():
            ids[key] = uuid.uuid4()
            if role == "child":
                await conn.execute(
                    "INSERT INTO users (id,username,display_name,pin_hash) VALUES ($1,$2,$3,$4);",
                    ids[key],
                    key,
                    key,
                    hash_password("1234"),
                )
            else:
                await conn.execute(
                    "INSERT INTO users (id,email,display_name,password_hash) VALUES ($1,$2,$3,$4);",
                    ids[key],
                    f"{key}@example.org",
                    key,
                    hash_password(PASSWORD),
                )
            await conn.execute(
                "INSERT INTO memberships (household_id,user_id,role) VALUES ($1,$2,$3);",
                ids["household"],
                ids[key],
                role,
            )
    finally:
        await conn.close()
    return ids


async def _leave(ids: dict[str, uuid.UUID], who: str) -> None:
    from app.kernel.tenancy.session import scoped_session
    from app.modules.accounts import service

    async with scoped_session(household_id=ids["household"], user_id=ids[who]) as session:
        await service.leave_household(session, user_id=ids[who], household_id=ids["household"])


async def _state(pg: PgDatabase, user_id: uuid.UUID) -> tuple[int, int]:
    """(lebende Mitgliedschaften, `member.left`-Ereignisse) für diese Person."""
    conn = await _su(pg)
    try:
        live = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE user_id=$1 AND deleted_at IS NULL;", user_id
        )
        events = await conn.fetchval(
            "SELECT count(*) FROM events_outbox WHERE type='member.left' "
            "AND payload->>'user_id' = $1;",
            str(user_id),
        )
    finally:
        await conn.close()
    return int(live), int(events)


# --- die reine Invariante, ohne Datenbank ---------------------------------------------------------


@pytest.mark.parametrize(
    ("other_roles", "expected"),
    [
        ((), None),
        (("admin",), None),
        (("admin", "child"), None),
        (("member",), "last_admin"),
        (("member", "child"), "last_admin"),
        (("guest",), "only_children"),
        (("child",), "only_children"),
        (("child", "child", "guest"), "only_children"),
    ],
)
def test_exit_blocker_reason_is_a_pure_decision(
    other_roles: tuple[str, ...], expected: str | None
) -> None:
    """Der Kern beider Pfade. ``guest`` zählt bewusst zu ``only_children``: ein Gast kann die
    Verwaltung so wenig übernehmen wie ein Kind, auch wenn er erwachsen ist."""
    from app.modules.accounts.service import exit_blocker_reason

    assert exit_blocker_reason(other_roles) == expected


# --- der Erfolgsfall ------------------------------------------------------------------------------


async def test_a_member_can_leave_and_the_access_ends(pg: PgDatabase, db: None) -> None:
    """Erst beweisen, dass die Mitgliedschaft lebte — sonst bestünde der Test
    auch bei leerem Seed."""
    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})

    live_before, events_before = await _state(pg, ids["mitbewohner"])
    assert (live_before, events_before) == (1, 0), (
        "Vorbedingung: Mitgliedschaft lebt, kein Ereignis"
    )

    await _leave(ids, "mitbewohner")

    live_after, events_after = await _state(pg, ids["mitbewohner"])
    assert live_after == 0, "die Mitgliedschaft muss beendet sein"
    assert events_after == 1, "ohne `member.left` laufen die vier Handler nie"


async def test_leaving_does_not_touch_anybody_else(pg: PgDatabase, db: None) -> None:
    """Gegenprobe zum Erfolgsfall: der Austritt trifft genau eine Zeile."""
    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member", "kind": "child"})

    await _leave(ids, "mitbewohner")

    for who in ("chef", "kind"):
        live, events = await _state(pg, ids[who])
        assert (live, events) == (1, 0), f"{who} darf unberührt bleiben"


async def test_leaving_revokes_every_live_session(pg: PgDatabase, db: None) -> None:
    """Der Widerruf steckt in geteiltem Code (``revoke_all_sessions``) — aber „geteilt" ist kein
    Beweis für „verdrahtet". Genau dieser Fehlschluss ließ den Löschantrag ohne ``member.left``
    ausliefern. Also: zwei lebende Sitzungen anlegen, danach nachzählen.

    Warum es zählt: ``Principal`` wird aus dem opaken Access-Token gebaut und je Anfrage **nicht**
    gegen die Datenbank geprüft. Ohne Widerruf behielte die Person bis zu 15 Minuten vollen Zugriff
    auf genau den Haushalt, den sie gerade verlassen hat.
    """
    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})

    conn = await _su(pg)
    try:
        for _ in range(2):
            await conn.execute(
                "INSERT INTO auth_sessions (user_id, family_id, refresh_hash, expires_at) "
                "VALUES ($1,$2,$3, now() + interval '30 days');",
                ids["mitbewohner"],
                uuid.uuid4(),
                uuid.uuid4().hex,
            )
        live_before = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id=$1 AND revoked_at IS NULL;",
            ids["mitbewohner"],
        )
    finally:
        await conn.close()
    assert live_before == 2, "Vorbedingung: es gibt etwas zu widerrufen"

    await _leave(ids, "mitbewohner")

    conn = await _su(pg)
    try:
        live_after = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id=$1 AND revoked_at IS NULL;",
            ids["mitbewohner"],
        )
        untouched = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id=$1 AND revoked_at IS NULL;",
            ids["chef"],
        )
    finally:
        await conn.close()
    assert live_after == 0, "jede Sitzung der ausgetretenen Person muss enden"
    assert untouched == 0, "und niemand sonst hatte eine — Gegenprobe zum Zähler oben"


async def test_removal_by_an_admin_revokes_the_sessions_too(pg: PgDatabase, db: None) -> None:
    """Der Zwilling des Tests darüber — und der, der zählt.

    Beim **Selbst**-Austritt ist ``app.user_id`` zufällig genau die Person, deren Sitzungen
    widerrufen werden; das Policy-Prädikat auf ``auth_sessions`` (``user_id = app.user_id``, mit
    FORCE) passt also. Beim **Entfernen durch einen Admin** läuft dieselbe Funktion auf der Session
    des *Admins* — und trifft null Zeilen. Ein Test, der nur den Selbstpfad prüft, sieht davon
    nichts (BUGLOG 2026-08-01).
    """
    from app.kernel.tenancy.session import scoped_session
    from app.modules.accounts import service

    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})

    conn = await _su(pg)
    try:
        row = await conn.fetchrow(
            "SELECT id FROM memberships WHERE user_id=$1;", ids["mitbewohner"]
        )
        membership_id = row["id"]
        for _ in range(2):
            await conn.execute(
                "INSERT INTO auth_sessions (user_id, family_id, refresh_hash, expires_at) "
                "VALUES ($1,$2,$3, now() + interval '30 days');",
                ids["mitbewohner"],
                uuid.uuid4(),
                uuid.uuid4().hex,
            )
        live_before = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id=$1 AND revoked_at IS NULL;",
            ids["mitbewohner"],
        )
    finally:
        await conn.close()
    assert live_before == 2, "Vorbedingung: es gibt etwas zu widerrufen"

    # Genau die Session-Form, die der Router benutzt: gescopt auf den handelnden Admin.
    async with scoped_session(household_id=ids["household"], user_id=ids["chef"]) as session:
        families = await service.remove_member(
            session, membership_id=membership_id, household_id=ids["household"]
        )

    conn = await _su(pg)
    try:
        live_after = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE user_id=$1 AND revoked_at IS NULL;",
            ids["mitbewohner"],
        )
    finally:
        await conn.close()

    assert live_after == 0, (
        "Ein entferntes Mitglied behielte sonst bis zu 15 Minuten Zugriff — und weil `refresh` "
        "den Haushalts-Scope aus Redis holt, rollierend deutlich länger."
    )
    assert families, "ohne Familien ist `burn_access_families` ein No-op"


async def test_a_child_cannot_lock_itself_out(pg: PgDatabase, db: None) -> None:
    """Die erste Fassung ließ das zu — mit der Begründung „der Austritt ist ein Recht der Person,
    keine Frage der Rolle". Das stimmt für Erwachsene und ist für ein Kinder-Konto falsch:

    Es hat weder E-Mail noch Passwort. ``child_login`` verlangt eine **lebende** Mitgliedschaft,
    ``accept_invite`` verlangt eine Sitzung, die das Kind ohne Login nicht herstellen kann, und
    ``create_child`` legt eine **neue** user id an — das alte Konto bliebe samt Punkten und
    Beiträgen verwaist. Hinter einem einzigen `window.confirm` war das keine Rechtsausübung,
    sondern eine Falltür. Der Kontrast im selben Slice ist das Argument: die Kontolöschung, gleich
    endgültig, bekommt Karenzfrist, zwei Schritte und eine Folgenliste.
    """
    from app.kernel.http.problem import ProblemException

    ids = await _seed(pg, {"chef": "admin", "kind": "child"})

    with pytest.raises(ProblemException) as caught:
        await _leave(ids, "kind")
    assert caught.value.slug == "child_cannot_leave"
    assert (await _state(pg, ids["kind"])) == (1, 0)


async def test_an_admin_can_still_remove_a_child(pg: PgDatabase, db: None) -> None:
    """Die Gegenprobe zum Test darüber: der Weg, den die Fehlermeldung nennt, existiert wirklich.
    Ohne diesen Test wäre `child_cannot_leave` eine Sackgasse, die nur behauptet, keine zu sein."""
    from app.kernel.tenancy.session import scoped_session
    from app.modules.accounts import service

    ids = await _seed(pg, {"chef": "admin", "kind": "child"})

    conn = await _su(pg)
    try:
        membership_id = await conn.fetchval(
            "SELECT id FROM memberships WHERE user_id=$1;", ids["kind"]
        )
    finally:
        await conn.close()

    async with scoped_session(household_id=ids["household"], user_id=ids["chef"]) as session:
        await service.remove_member(
            session, membership_id=membership_id, household_id=ids["household"]
        )

    assert (await _state(pg, ids["kind"])) == (0, 1)


# --- die drei Abweisungen -------------------------------------------------------------------------


async def test_the_last_admin_beside_adults_is_refused(pg: PgDatabase, db: None) -> None:
    """Behebbar: es gibt jemanden, der übernehmen kann. Die Meldung sagt das auch."""
    from app.kernel.http.problem import ProblemException

    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})

    with pytest.raises(ProblemException) as caught:
        await _leave(ids, "chef")
    assert caught.value.slug == "last_admin"

    live, events = await _state(pg, ids["chef"])
    assert (live, events) == (1, 0), "ein abgelehnter Austritt darf nichts verändern"


async def test_the_last_admin_beside_only_children_is_refused_with_its_own_reason(
    pg: PgDatabase, db: None
) -> None:
    """Unbehebbar — und deshalb ein eigener Grund. Beide Fälle gleich zu benennen hieße, der Person
    „übertrage zuerst" zu sagen, wo es niemanden gibt, dem sie übertragen könnte."""
    from app.kernel.http.problem import ProblemException

    ids = await _seed(pg, {"chef": "admin", "kind": "child", "gast": "guest"})

    with pytest.raises(ProblemException) as caught:
        await _leave(ids, "chef")
    assert caught.value.slug == "only_children"
    assert (await _state(pg, ids["chef"])) == (1, 0)


async def test_the_sole_member_is_refused(pg: PgDatabase, db: None) -> None:
    """Das wäre kein Austritt, sondern eine Auflösung — und die kann heute noch niemand.
    Ein ehrliches Nein ist besser als eine Schaltfläche, die Daten verwaisen lässt."""
    from app.kernel.http.problem import ProblemException

    ids = await _seed(pg, {"chef": "admin"})

    with pytest.raises(ProblemException) as caught:
        await _leave(ids, "chef")
    assert caught.value.slug == "sole_member"
    assert (await _state(pg, ids["chef"])) == (1, 0)


async def test_a_second_admin_removes_the_block(pg: PgDatabase, db: None) -> None:
    """Der Weg heraus, den die Fehlermeldung nennt. Ohne diesen Test wäre ``last_admin`` eine
    Sackgasse, die nur behauptet, keine zu sein."""
    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})

    conn = await _su(pg)
    try:
        await conn.execute(
            "UPDATE memberships SET role='admin' WHERE user_id=$1;", ids["mitbewohner"]
        )
    finally:
        await conn.close()

    await _leave(ids, "chef")
    assert (await _state(pg, ids["chef"]))[0] == 0


# --- die Invariante hält auch gegen Gleichzeitigkeit ----------------------------------------------


async def test_two_admins_leaving_at_once_cannot_empty_the_household(
    pg: PgDatabase, db: None
) -> None:
    """Der Fall, den ein Einzeltest nie sieht (BUGLOG 2026-08-01).

    Beide Austritte prüfen den Bestand, beide sehen „es gibt ja noch einen zweiten Admin", beide
    gehen. Unter READ COMMITTED und ohne Sperre sahen sie einander nicht — zurück blieb ein
    Haushalt mit **null** Admins, und weil Einladungen *und* Rollenwechsel Admin-Rechte verlangen,
    gab es daraus keinen Weg heraus.

    Der Test ist absichtlich über die *Wirkung* formuliert, nicht über die Sperre: welcher der
    beiden gewinnt, ist gleichgültig und darf sich ändern. Was nicht darf, ist ein Haushalt ohne
    Verwaltung.
    """
    ids = await _seed(pg, {"a": "admin", "b": "admin", "kind": "child"})

    results = await asyncio.gather(_leave(ids, "a"), _leave(ids, "b"), return_exceptions=True)
    failures = [r for r in results if isinstance(r, BaseException)]

    conn = await _su(pg)
    try:
        admins_left = await conn.fetchval(
            "SELECT count(*) FROM memberships "
            "WHERE household_id=$1 AND role='admin' AND deleted_at IS NULL;",
            ids["household"],
        )
    finally:
        await conn.close()

    assert admins_left >= 1, "Admin-Kontinuität — die Invariante steht als hart in der Modul-Doku"
    assert len(failures) == 1, "genau einer der beiden muss abgewiesen worden sein"


# --- der bewusste Unterschied zur Kontolöschung ---------------------------------------------------


async def test_the_two_paths_disagree_about_the_solo_household(pg: PgDatabase, db: None) -> None:
    """Derselbe Haushalt, zwei Antworten — und das ist richtig so.

    Der Austritt lehnt ab (es gibt ein „stattdessen": den Haushalt auflösen). Die Kontolöschung
    lässt zu, denn dort gibt es keines: Art. 17 ist ein Recht, und der Haushalt endet mit der
    einzigen Person darin. Wer die beiden später vereinheitlicht, sperrt entweder jemanden aus
    seinem Löschrecht aus oder lässt verwaiste Haushalte zurück.
    """
    from app.kernel.http.problem import ProblemException
    from app.modules.accounts import service

    ids = await _seed(pg, {"chef": "admin"})

    with pytest.raises(ProblemException) as caught:
        await _leave(ids, "chef")
    assert caught.value.slug == "sole_member"

    assert await service.account_deletion_blockers(user_id=ids["chef"]) == []
    await service.request_account_deletion(user_id=ids["chef"])
    assert (await _state(pg, ids["chef"])) == (0, 1)
