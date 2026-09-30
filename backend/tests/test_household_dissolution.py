"""Die Auflösung eines Haushalts (Art. 17, KONZEPT §5.1, ADR-0085).

Sie ist die Operation, die zwei Sackgassen öffnet: `sole_member` beim Selbst-Austritt,
`only_children` bei der Kontolöschung. Beide verwiesen auf sie, und niemand konnte sie ausführen.

Drei Dinge prüft diese Datei, und jedes hat einen Vorfall hinter sich:

1. **Der Zugang endet sofort und überall** — Sitzungen, und die vier Eintrittstüren, die
   `households.deleted_at` bis zu diesem Slice nicht lasen. Jeder Test beweist erst das Vorher.
2. **Kinder-Konten enden mit.** Sie haben kein Login außerhalb des Haushalts und wären sonst
   unerreichbar *und* von keinem Löschjob erfassbar.
3. **Der Ökonomie-Handler ist verdrahtet**, nicht nur vorhanden. Beim Löschantrag (11-S1c) war
   genau das der Fehler: die Funktion existierte, das Ereignis wurde nie emittiert.

Ohne Docker übersprungen.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import asyncpg
import pytest

from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase

BACKEND_DIR = Path(__file__).resolve().parents[1]
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
    from app.kernel.auth.passwords import hash_password

    ids: dict[str, uuid.UUID] = {"household": uuid.uuid4()}
    conn = await _su(pg)
    try:
        await conn.execute(
            "TRUNCATE households, users, memberships, auth_sessions, events_outbox, invites "
            "CASCADE;"
        )
        await conn.execute(
            "INSERT INTO households (id,name) VALUES ($1,'WG Nord');", ids["household"]
        )
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


async def _dissolve(ids: dict[str, uuid.UUID], actor: str) -> set[uuid.UUID]:
    from app.kernel.tenancy.session import scoped_session
    from app.modules.accounts import service

    async with scoped_session(household_id=ids["household"], user_id=ids[actor]) as session:
        return await service.dissolve_household(
            session, household_id=ids["household"], actor_id=ids[actor]
        )


# --- Der Kern: alle gehen, der Haushalt ist zu ----------------------------------------------------


async def test_dissolving_ends_every_membership_and_every_session(pg: PgDatabase, db: None) -> None:
    """Erst zählen, dann auflösen, dann nachzählen — für **jedes** Mitglied.

    Der Sitzungs-Widerruf ist hier besonders heikel: er trifft fremde Zeilen, und genau dort hat
    `revoke_all_sessions` monatelang null Zeilen getroffen (BUGLOG 2026-08-01). Dass die Funktion
    inzwischen richtig ist, beweist ihr eigener Test — dass sie hier **aufgerufen** wird, nur
    dieser.
    """
    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member", "kind": "child"})

    conn = await _su(pg)
    try:
        for key in ("chef", "mitbewohner", "kind"):
            await conn.execute(
                "INSERT INTO auth_sessions (user_id,family_id,refresh_hash,expires_at) "
                "VALUES ($1,$2,$3, now() + interval '30 days');",
                ids[key],
                uuid.uuid4(),
                uuid.uuid4().hex,
            )
        live_before = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE deleted_at IS NULL;"
        )
        sessions_before = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL;"
        )
    finally:
        await conn.close()
    assert (live_before, sessions_before) == (3, 3), "Vorbedingung: drei Mitglieder, drei Sitzungen"

    families = await _dissolve(ids, "chef")
    assert len(families) == 3, "die Familien ALLER Mitglieder müssen zum Verbrennen zurückkommen"

    conn = await _su(pg)
    try:
        live_after = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE deleted_at IS NULL;"
        )
        sessions_after = await conn.fetchval(
            "SELECT count(*) FROM auth_sessions WHERE revoked_at IS NULL;"
        )
        household_gone = await conn.fetchval(
            "SELECT deleted_at IS NOT NULL FROM households WHERE id=$1;", ids["household"]
        )
    finally:
        await conn.close()
    assert live_after == 0
    assert sessions_after == 0, "sonst behielte jedes Mitglied bis zu 15 Minuten vollen Zugriff"
    assert household_gone is True


async def test_the_last_admin_may_dissolve_although_no_other_operation_would_let_them(
    pg: PgDatabase, db: None
) -> None:
    """Die Admin-Kontinuität wird hier freigegeben, nicht umgangen.

    Gegenprobe zur Invariante: derselbe Admin, der weder austreten (`last_admin`) noch sich
    herabstufen dürfte, darf auflösen. Wäre das nicht so, bliebe `only_children` eine Sackgasse.
    """
    from app.kernel.http.problem import ProblemException
    from app.kernel.tenancy.session import scoped_session
    from app.modules.accounts import service

    ids = await _seed(pg, {"chef": "admin", "kind": "child"})

    # Vorher: austreten geht NICHT — das ist der Zustand, den die Auflösung auflöst.
    with pytest.raises(ProblemException) as caught:
        async with scoped_session(household_id=ids["household"], user_id=ids["chef"]) as session:
            await service.leave_household(
                session, user_id=ids["chef"], household_id=ids["household"]
            )
    assert caught.value.slug == "only_children"

    await _dissolve(ids, "chef")

    conn = await _su(pg)
    try:
        assert await conn.fetchval(
            "SELECT deleted_at IS NOT NULL FROM households WHERE id=$1;", ids["household"]
        )
    finally:
        await conn.close()


async def test_a_second_dissolution_is_refused_rather_than_repeated(
    pg: PgDatabase, db: None
) -> None:
    """Ein zweiter Lauf erzeugte sonst ein zweites `household.dissolved` — ein Ereignis ohne
    Anlass ist eine Lüge im Protokoll, auch wenn die Handler idempotent sind."""
    from app.kernel.http.problem import ProblemException

    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})
    await _dissolve(ids, "chef")

    with pytest.raises(ProblemException) as caught:
        await _dissolve(ids, "chef")
    assert caught.value.slug == "already_dissolved"


# --- Kinder ---------------------------------------------------------------------------------------


async def test_child_accounts_are_marked_for_deletion_with_the_household(
    pg: PgDatabase, db: None
) -> None:
    """Ein Kinder-Konto hat kein Login außerhalb des Haushalts (kein Passwort, keine E-Mail, und
    `child_login` verlangt eine lebende Mitgliedschaft). Bliebe es stehen, wäre es **unerreichbar
    und von keinem Löschjob erfassbar** — der Konto-Purge hängt an `users.deleted_at`, und das kann
    sonst nur die Person selbst setzen."""
    ids = await _seed(pg, {"chef": "admin", "kind": "child", "zweitkind": "child"})

    conn = await _su(pg)
    try:
        marked_before = await conn.fetchval(
            "SELECT count(*) FROM users WHERE deleted_at IS NOT NULL;"
        )
    finally:
        await conn.close()
    assert marked_before == 0, "Vorbedingung: noch ist kein Konto vorgemerkt"

    await _dissolve(ids, "chef")

    conn = await _su(pg)
    try:
        rows = await conn.fetch("SELECT id, deleted_at FROM users ORDER BY display_name;")
    finally:
        await conn.close()
    marked = {r["id"] for r in rows if r["deleted_at"] is not None}
    assert marked == {ids["kind"], ids["zweitkind"]}, (
        "genau die Kinder-Konten — und ausdrücklich NICHT das des Admins: Erwachsene behalten ihr "
        "Konto und ihr eigenes Löschrecht"
    )


# --- Der Handler ist verdrahtet, nicht nur vorhanden ----------------------------------------------


async def test_the_dissolution_event_is_emitted_and_has_a_registered_handler(
    pg: PgDatabase, db: None
) -> None:
    """Der Fehler aus 11-S1c, eine Ebene höher.

    Damals existierte die Funktion und das Ereignis wurde nie emittiert — vier Handler liefen
    deshalb nie. Hier wird beides geprüft: das Ereignis liegt in der Outbox, **und** der
    Composition Root registriert einen Handler dafür. Ein Import allein ist kein Beweis; beim
    Schreiben dieses Slices stand `register_household_dissolution_handler` bereits importiert im
    Worker, ohne aufgerufen zu werden.
    """
    from app.household_dissolution import register_household_dissolution_handler
    from app.kernel.events.dispatcher import OutboxDispatcher

    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})
    await _dissolve(ids, "chef")

    conn = await _su(pg)
    try:
        events = await conn.fetch("SELECT type FROM events_outbox ORDER BY type;")
    finally:
        await conn.close()
    types = [e["type"] for e in events]
    assert types.count("household.dissolved") == 1
    assert types.count("member.left") == 2, "je Mitglied eines — die vier Handler hängen daran"

    dispatcher = OutboxDispatcher()
    register_household_dissolution_handler(dispatcher)
    assert dispatcher._handlers.get("household.dissolved"), (
        "das Ereignis ohne Handler wäre genau der Fehler aus 11-S1c"
    )

    # Und der Composition Root muss ihn auch wirklich AUFRUFEN. Beim Bauen dieses Slices stand der
    # Import bereits im Worker, ohne dass der Aufruf danebenstand — ein Import ist kein Beweis.
    worker_source = (BACKEND_DIR / "app" / "worker.py").read_text()
    assert "register_household_dissolution_handler(get_dispatcher())" in worker_source


async def test_the_member_exit_handler_stands_down_for_a_dissolved_household(
    pg: PgDatabase, db: None
) -> None:
    """Sonst zögen zwei Worker `household.dissolved` und ein `member.left` gleichzeitig, und die
    Reihenfolge der Ökonomie wäre wieder offen — freigegebenes Escrow käme nach dem Verfall an."""
    from app.kernel.events.envelope import EventEnvelope
    from app.member_exit import on_member_left

    ids = await _seed(pg, {"chef": "admin", "mitbewohner": "member"})
    await _dissolve(ids, "chef")

    # Der Aufruf muss folgenlos durchlaufen — er darf nicht scheitern und nichts abwickeln.
    await on_member_left(
        EventEnvelope(
            type="member.left",
            household_id=ids["household"],
            occurred_at=datetime.now(UTC),
            payload={"user_id": str(ids["mitbewohner"])},
        )
    )


# --- Befunde des adversarialen Durchgangs ---------------------------------------------------------


async def test_an_adult_demoted_to_child_keeps_their_account(pg: PgDatabase, db: None) -> None:
    """Der schwerste Fund dieses Slices, und er war meiner.

    `child` ist eine **Mitgliedschafts**-Rolle, kein Kontotyp: ein Admin kann ein erwachsenes
    Mitglied per `PATCH /v1/household/members/{id}` auf `child` herabstufen. Mit „Rolle == child"
    als Bedingung hätte er damit über die Auflösung dessen **Konto** zur endgültigen Löschung
    vorgemerkt — haushaltsübergreifend, ohne Zustimmung, ohne Rücknahme, und in 30 Tagen räumt der
    Purge es aus. Aus einer Verwaltungsbefugnis wäre eine Konto-Vernichtungs-Primitive geworden.

    Geprüft wird deshalb die Eigenschaft, die den Tombstone rechtfertigt: kein eigener Anmeldeweg.
    """
    from app.kernel.tenancy.session import scoped_session
    from app.modules.accounts import service

    ids = await _seed(pg, {"chef": "admin", "erwachsener": "member"})

    conn = await _su(pg)
    try:
        membership_id = await conn.fetchval(
            "SELECT id FROM memberships WHERE user_id=$1;", ids["erwachsener"]
        )
    finally:
        await conn.close()

    async with scoped_session(household_id=ids["household"], user_id=ids["chef"]) as session:
        await service.change_role(
            session,
            membership_id=membership_id,
            new_role="child",
            household_id=ids["household"],
        )

    await _dissolve(ids, "chef")

    conn = await _su(pg)
    try:
        row = await conn.fetchrow(
            "SELECT email, deleted_at FROM users WHERE id=$1;", ids["erwachsener"]
        )
    finally:
        await conn.close()
    assert row is not None and row["email"] == "erwachsener@example.org"
    assert row["deleted_at"] is None, (
        "Ein Konto mit E-Mail kann sich zurückholen (Passwort-Reset) — es stirbt nicht mit einem "
        "Haushalt, egal welche Rolle die Mitgliedschaft trug."
    )


async def test_a_child_account_with_another_household_survives(pg: PgDatabase, db: None) -> None:
    """Die zweite Bedingung. Ein Kinder-Konto, das anderswo noch eine lebende Mitgliedschaft hat,
    bleibt dort erreichbar — es mit diesem Haushalt zu beenden wäre schlicht falsch."""
    ids = await _seed(pg, {"chef": "admin", "kind": "child"})

    other = uuid.uuid4()
    conn = await _su(pg)
    try:
        await conn.execute("INSERT INTO households (id,name) VALUES ($1,'Zweitfamilie');", other)
        await conn.execute(
            "INSERT INTO memberships (household_id,user_id,role) VALUES ($1,$2,'child');",
            other,
            ids["kind"],
        )
    finally:
        await conn.close()

    await _dissolve(ids, "chef")

    conn = await _su(pg)
    try:
        marked = await conn.fetchval("SELECT deleted_at FROM users WHERE id=$1;", ids["kind"])
    finally:
        await conn.close()
    assert marked is None, "das Kind ist im zweiten Haushalt weiterhin erreichbar"


async def test_a_rollback_leaves_no_account_marked_for_deletion(pg: PgDatabase, db: None) -> None:
    """Der zweite schwere Fund: der Kinder-Tombstone lief in einer **eigenen** Transaktion und
    committete sofort.

    Rollt die äußere Transaktion danach zurück — im Router genügt ein Redis-Ausfall im
    anschließenden `burn_access_families` —, stünde ein **lebender** Haushalt mit vorgemerkten
    Kinder-Konten da. Unwiderruflich, unbemerkt, und die Kinder könnten es selbst nicht sehen.

    Der Test bildet genau das ab: auflösen, dann zurückrollen. Danach muss **alles** unberührt
    sein, auch das Konto.
    """
    from app.kernel.db.engine import get_sessionmaker
    from app.kernel.tenancy.session import _apply_scope
    from app.modules.accounts import service

    ids = await _seed(pg, {"chef": "admin", "kind": "child"})

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        await _apply_scope(session, str(ids["household"]), str(ids["chef"]))
        await service.dissolve_household(
            session, household_id=ids["household"], actor_id=ids["chef"]
        )
        await session.rollback()

    conn = await _su(pg)
    try:
        household = await conn.fetchval(
            "SELECT deleted_at FROM households WHERE id=$1;", ids["household"]
        )
        child = await conn.fetchval("SELECT deleted_at FROM users WHERE id=$1;", ids["kind"])
        live = await conn.fetchval("SELECT count(*) FROM memberships WHERE deleted_at IS NULL;")
    finally:
        await conn.close()

    assert household is None, "Vorbedingung des Tests: die äußere Transaktion wurde zurückgerollt"
    assert live == 2, "die Mitgliedschaften leben wieder"
    assert child is None, (
        "und das Konto darf NICHT vorgemerkt sein — sonst überlebte eine unwiderrufliche "
        "Löschvormerkung einen Vorgang, der gar nicht stattgefunden hat"
    )


async def test_the_feed_revocation_does_not_hang_on_the_caldav_handler(
    pg: PgDatabase, db: None
) -> None:
    """Dritter Fund: Feed-Widerruf und Abo-Löschung teilten sich eine Transaktion und einen
    Idempotenz-Schlüssel. Ein CalDAV-Abo mit einer Besonderheit rollte damit die Entwertung des
    **unauthentifizierten** Feed-Tokens mit zurück — und nach fünf Versuchen bliebe er dauerhaft
    offen. Der Token ist die einzige Zugangskontrolle dieser Route; er darf nicht an der
    schwächeren Zusage hängen."""
    from app.kernel.events.dispatcher import OutboxDispatcher
    from app.modules.calendar.handlers import register_calendar_handlers

    dispatcher = OutboxDispatcher()
    register_calendar_handlers(dispatcher)
    names = [name for name, _ in dispatcher._handlers["member.left"]]
    assert names == [
        "calendar.revoke_feed_on_member_left",
        "calendar.revoke_on_member_left",
    ], "zwei Handler, Feed zuerst — getrennte Transaktionen und getrennte Retry-Zähler"


# --- Der erfüllte Handel in der Auflösung (BUGLOG 2026-08-03) -------------------------------------


async def test_the_settlement_survives_a_delivered_but_unsettled_trade(
    pg: PgDatabase, db: None
) -> None:
    """Hier war der Schaden größer als beim Einzelaustritt — und zwar aus einem Grund, der in der
    Datei nebenan steht: ``settle_household_dissolution`` fährt **alle** Mitglieder in **einer**
    Transaktion, weil ``revert_listing`` den Verkäufer kreditiert und dessen Saldo sonst schon
    verfallen sein könnte. Genau diese eine Transaktion machte aus einem einzelnen kaputten
    Listing einen Totalausfall: keine Rückzüge, keine Aufgaben-Freigaben, keine Punkte-Verfälle —
    für niemanden.

    Der Test beweist erst das Vorher (Escrow gebunden, Listing ``accepted``), dann den Vorgang.
    """
    from app.household_dissolution import settle_household_dissolution

    ids = await _seed(pg, {"admin": "admin", "kaeufer": "member"})
    listing_id, instance_id = uuid.uuid4(), uuid.uuid4()
    conn = await _su(pg)
    try:
        await conn.execute(
            "INSERT INTO points_ledger "
            "(household_id, from_account, to_account, amount, ref_type) "
            "VALUES ($1,'system',$2,50,'task_completion');",
            ids["household"],
            f"member:{ids['admin']}",
        )
        await conn.execute(
            "INSERT INTO task_instances (id, household_id, title, points, assigned_to, status) "
            "VALUES ($1,$2,'Geliefert',10,$3,'done');",
            instance_id,
            ids["household"],
            ids["kaeufer"],
        )
        await conn.execute(
            "INSERT INTO market_listings "
            "(id, household_id, task_instance_id, title, seller_id, price, status, buyer_id) "
            "VALUES ($1,$2,$3,'Geliefert',$4,20,'accepted',$5);",
            listing_id,
            ids["household"],
            instance_id,
            ids["admin"],
            ids["kaeufer"],
        )
        await conn.execute(
            "INSERT INTO points_ledger "
            "(household_id, from_account, to_account, amount, ref_type, ref_id) "
            "VALUES ($1,$2,$3,20,'market_escrow',$4);",
            ids["household"],
            f"member:{ids['admin']}",
            f"escrow:{listing_id}",
            listing_id,
        )
        escrow_before = await conn.fetchval(
            "SELECT coalesce(sum(amount),0) FROM points_ledger WHERE to_account = $1;",
            f"escrow:{listing_id}",
        )
    finally:
        await conn.close()
    assert escrow_before == 20, "Vorher: das Escrow liegt wirklich gebunden"

    settlement = await settle_household_dissolution(household_id=ids["household"])

    conn = await _su(pg)
    try:
        status = await conn.fetchval(
            "SELECT status FROM market_listings WHERE id = $1;", listing_id
        )
        leftovers = await conn.fetch(
            "SELECT to_account, sum(amount) AS s FROM points_ledger "
            "WHERE to_account LIKE 'member:%' GROUP BY to_account;"
        )
    finally:
        await conn.close()

    assert settlement.members == 2
    assert status == "settled"
    # Der eigentliche Beweis: Schritt 3 lief. Kein Mitgliedskonto trägt nach der Auflösung
    # noch einen Saldo — vorher scheiterte die Transaktion, bevor sie hier ankam.
    assert settlement.points_expired > 0
    assert leftovers, "Sanity: es gab überhaupt Buchungen auf Mitgliedskonten"
