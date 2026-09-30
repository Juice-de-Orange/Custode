"""Verlässt jemand den Haushalt, endet sein Zugang — überall (KONZEPT §5.1, 11-S1a).

Bisher setzte `remove_member` ein Tombstone auf die Mitgliedschaft und emittierte `member.left`,
und das Ereignis hatte keinen einzigen Fach-Handler. Drei Wege blieben offen, und der erste ist
der ernste:

1. **Der ICS-Feed-Token.** ``GET /v1/calendar/feed/<token>.ics`` ist unauthentifiziert (ADR-0042 —
   Kalender-Apps schicken keine Cookies). Die einzige Zugangskontrolle ist der Token. Er überlebte
   die Entfernung **dauerhaft**: kein Cookie, keine Rolle, kein Ablauf.
2. **Die Sitzung.** ``Principal`` wird aus dem opaken Access-Token gebaut, nicht je Anfrage gegen
   die Datenbank geprüft — das Token trägt `household_id` und `role` in sich. Bis zu 15 Minuten
   voller Zugriff auf den Haushalt, aus dem gerade entfernt wurde.
3. **CalDAV-Abo und Wearable-Verbindung.** Beide gehören der Person, beide liefen weiter.

Die Tests hier sind so gebaut, dass jeder erst das **Vorher** beweist. Ein Test, der nur „nachher
kein Zugriff" prüft, bestünde auch, wenn der Zugriff nie funktioniert hätte.

Ohne Docker übersprungen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import asyncpg
import pytest

from app.kernel.db import engine as engine_mod
from app.settings import get_settings
from conftest import PgDatabase


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    import os

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


@pytest.fixture
async def world(pg: PgDatabase, db: None) -> dict[str, uuid.UUID]:
    """Ein Haushalt, ein Admin, ein Mitglied — das Mitglied hat Feed, Abo und Wearable."""
    ids = {"household": uuid.uuid4(), "admin": uuid.uuid4(), "member": uuid.uuid4()}
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await conn.execute("TRUNCATE households, users, memberships CASCADE;")
        await conn.execute(
            "TRUNCATE calendar_feeds, external_calendar_subscriptions, wearable_connections,"
            " wearable_daily, calendar_events CASCADE;"
        )
        await conn.execute(
            "INSERT INTO households (id, name) VALUES ($1,'Testhaushalt');", ids["household"]
        )
        for key, role in (("admin", "admin"), ("member", "member")):
            await conn.execute(
                "INSERT INTO users (id, email, display_name) VALUES ($1,$2,$3);",
                ids[key],
                f"{key}@example.org",
                key,
            )
            await conn.execute(
                "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,$3);",
                ids["household"],
                ids[key],
                role,
            )
        await conn.execute(
            "INSERT INTO calendar_feeds (household_id, member_id, token) VALUES ($1,$2,$3);",
            ids["household"],
            ids["member"],
            "feed-token-des-mitglieds",
        )
        await conn.execute(
            "INSERT INTO external_calendar_subscriptions "
            "(household_id, member_id, label, caldav_url) VALUES ($1,$2,'Privat',$3);",
            ids["household"],
            ids["member"],
            "https://cloud.example/remote.php/dav/calendars/privat/",
        )
        await conn.execute(
            "INSERT INTO wearable_connections (household_id, member_id, provider, tokens_enc) "
            "VALUES ($1,$2,'oura','v1:token');",
            ids["household"],
            ids["member"],
        )
        await conn.execute(
            "INSERT INTO wearable_daily (household_id, member_id, provider, day, sleep_score) "
            "VALUES ($1,$2,'oura',CURRENT_DATE,70);",
            ids["household"],
            ids["member"],
        )
        # Die erteilte Einwilligung, die der Austritt widerrufen muss.
        await conn.execute(
            "INSERT INTO consents (household_id, subject_user_id, type, action, granted_by) "
            "VALUES ($1,$2,'wearable_sleep','grant',$2);",
            ids["household"],
            ids["member"],
        )
    finally:
        await conn.close()
    return ids


async def _su(pg: PgDatabase) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )


async def _fire_member_left(ids: dict[str, uuid.UUID]) -> None:
    """**Alle registrierten** Handler aufrufen, so wie der Dispatcher es täte.

    Bewusst über die Registrierung statt über namentliche Importe. Die erste Fassung rief zwei
    Funktionen direkt auf — und als der Kalender-Slice den Feed-Widerruf 2026-08-01 in einen
    eigenen Handler auslagerte (damit ein CalDAV-Fehlschlag ihn nicht mit zurückrollt), prüfte
    dieser Test den Feed-Token nicht mehr. Er wurde rot, was gut ist; wäre er es nicht geworden,
    hätte er still aufgehört, das Wichtigste zu prüfen.

    Über die Registrierung zu gehen heißt: jeder künftig hinzugefügte oder aufgeteilte Handler ist
    automatisch mit abgedeckt.
    """
    from app.kernel.events.dispatcher import OutboxDispatcher
    from app.kernel.events.envelope import EventEnvelope
    from app.modules.calendar.handlers import register_calendar_handlers
    from app.modules.wearables.handlers import register_wearables_handlers

    dispatcher = OutboxDispatcher()
    register_calendar_handlers(dispatcher)
    register_wearables_handlers(dispatcher)

    envelope = EventEnvelope(
        type="member.left",
        household_id=ids["household"],
        occurred_at=datetime.now(UTC),
        payload={"membership_id": str(uuid.uuid4()), "user_id": str(ids["member"])},
    )
    handlers = dispatcher._handlers["member.left"]
    assert len(handlers) >= 3, "Kalender-Feed, Kalender-Abos, Wearables — mindestens drei"
    for _name, handler in handlers:
        await handler(envelope)


# --- der ICS-Feed-Token ---------------------------------------------------------------------


async def test_the_feed_token_stops_working_after_removal(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Der ernste Fall. Der Feed ist unauthentifiziert — der Token IST die Zugangskontrolle.

    Erst das Vorher: der Token löst auf. Dann der Austritt. Dann darf er nicht mehr auflösen.
    Ohne den ersten Teil bestünde dieser Test auch bei einem kaputten Seed.
    """
    su = await _su(pg)
    try:
        before = await su.fetchval(
            "SELECT count(*) FROM calendar_feeds WHERE token = $1 AND deleted_at IS NULL;",
            "feed-token-des-mitglieds",
        )
    finally:
        await su.close()
    assert before == 1, "Vorbedingung: der Feed muss vorher auflösen"

    await _fire_member_left(world)

    su = await _su(pg)
    try:
        after = await su.fetchval(
            "SELECT count(*) FROM calendar_feeds WHERE token = $1 AND deleted_at IS NULL;",
            "feed-token-des-mitglieds",
        )
    finally:
        await su.close()
    assert after == 0, "der Feed-Token eines entfernten Mitglieds darf nicht mehr auflösen"


# --- CalDAV-Abos ------------------------------------------------------------------------------


async def test_the_caldav_subscription_stops_syncing(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Sonst holte der 15-Minuten-Cron weiter Termine aus dem privaten Kalender einer Person, die
    nicht mehr dazugehört."""
    su = await _su(pg)
    try:
        assert (
            await su.fetchval(
                "SELECT count(*) FROM external_calendar_subscriptions WHERE deleted_at IS NULL;"
            )
            == 1
        )
    finally:
        await su.close()

    await _fire_member_left(world)

    su = await _su(pg)
    try:
        live = await su.fetchval(
            "SELECT count(*) FROM external_calendar_subscriptions WHERE deleted_at IS NULL;"
        )
    finally:
        await su.close()
    assert live == 0


# --- Wearables (Art. 9) -------------------------------------------------------------------------


async def test_health_data_is_hard_deleted_not_tombstoned(
    world: dict[str, uuid.UUID], pg: PgDatabase
) -> None:
    """Die Einwilligung galt für DIESEN Haushalt. Endet die Mitgliedschaft, endet die
    Rechtsgrundlage — und Art. 9 verlangt ein Löschen, das wirklich löscht (die Tabellen haben ein
    CHECK, das Tombstones verbietet)."""
    su = await _su(pg)
    try:
        assert await su.fetchval("SELECT count(*) FROM wearable_connections;") == 1
        assert await su.fetchval("SELECT count(*) FROM wearable_daily;") == 1
    finally:
        await su.close()

    await _fire_member_left(world)

    su = await _su(pg)
    try:
        assert await su.fetchval("SELECT count(*) FROM wearable_connections;") == 0
        assert await su.fetchval("SELECT count(*) FROM wearable_daily;") == 0
        # Der Consent-Ledger bleibt: er ist der Nachweis, dass eine Einwilligung bestand und endete.
        revoked = await su.fetchval(
            "SELECT count(*) FROM consents WHERE subject_user_id = $1 AND action = 'revoke';",
            world["member"],
        )
    finally:
        await su.close()
    assert revoked >= 1, "der Widerruf muss auditierbar bleiben"


# --- Idempotenz ---------------------------------------------------------------------------------


async def test_running_twice_changes_nothing(world: dict[str, uuid.UUID], pg: PgDatabase) -> None:
    """Outbox-Zustellung ist at-least-once. Ein zweiter Lauf muss folgenlos sein."""
    await _fire_member_left(world)
    await _fire_member_left(world)

    su = await _su(pg)
    try:
        assert await su.fetchval("SELECT count(*) FROM wearable_connections;") == 0
        assert (
            await su.fetchval(
                "SELECT count(*) FROM external_calendar_subscriptions WHERE deleted_at IS NULL;"
            )
            == 0
        )
    finally:
        await su.close()


async def test_a_payload_without_a_user_is_ignored(world: dict[str, uuid.UUID]) -> None:
    """Ein Ereignis ohne ``user_id`` darf nichts anfassen — nicht raten, nicht abstürzen."""
    from app.kernel.events.envelope import EventEnvelope
    from app.modules.calendar.handlers import on_member_left

    await on_member_left(
        EventEnvelope(
            type="member.left",
            household_id=world["household"],
            occurred_at=datetime.now(UTC),
            payload={},
        )
    )
