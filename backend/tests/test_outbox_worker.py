"""Outbox worker integration tests (Testcontainers Postgres 18): the hourly reaper
(``reap``) drops processed/ledger rows past retention while keeping recent and unprocessed
rows, runs cross-household as ``custode_maint``, and the worker drain loop processes due
events until the queue is idle. Skipped without Docker."""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.kernel.events.dispatcher import reap
from app.kernel.events.registry import get_dispatcher
from app.worker import drain_outbox
from conftest import PgDatabase


def _engine(pg: PgDatabase, user: str, password: str) -> AsyncEngine:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    return create_async_engine(f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{pg.dbname}")


async def _seed_processed(admin: AsyncEngine, *, household_id: uuid.UUID, days_ago: float) -> None:
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO events_outbox (type, household_id, payload, processed_at) "
                "VALUES ('reap.evt', :h, '{}'::jsonb, now() - make_interval(days => :d))"
            ),
            {"h": household_id, "d": days_ago},
        )


async def _seed_unprocessed(admin: AsyncEngine, *, household_id: uuid.UUID, etype: str) -> None:
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO events_outbox (type, household_id, payload) "
                "VALUES (:t, :h, '{}'::jsonb)"
            ),
            {"t": etype, "h": household_id},
        )


async def _seed_ledger(admin: AsyncEngine, *, handler: str, days_ago: float) -> None:
    async with admin.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO processed_events (handler, event_id, processed_at) "
                "VALUES (:h, :e, now() - make_interval(days => :d))"
            ),
            {"h": handler, "e": uuid.uuid4(), "d": days_ago},
        )


async def _count(admin: AsyncEngine, sql: str, params: dict | None = None) -> int:
    async with admin.connect() as conn:
        return await conn.scalar(text(sql), params or {})  # type: ignore[return-value]


async def test_reap_drops_old_processed_keeps_recent_and_unprocessed(pg: PgDatabase) -> None:
    admin = _engine(pg, pg.username, pg.password)
    maint = _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    h = uuid.uuid4()
    handler = f"reap-{h}"
    try:
        await _seed_processed(admin, household_id=h, days_ago=40)  # old -> reaped
        await _seed_processed(admin, household_id=h, days_ago=1)  # recent -> kept
        await _seed_unprocessed(admin, household_id=h, etype="reap.evt")  # unprocessed -> kept
        await _seed_ledger(admin, handler=handler, days_ago=40)  # old -> reaped
        await _seed_ledger(admin, handler=handler, days_ago=2)  # recent -> kept

        async with sm() as s:
            result = await reap(s, retention_days=30)

        assert result.outbox >= 1
        assert result.processed_events >= 1
        # For THIS household: the 40-day processed row is gone; recent + unprocessed remain.
        assert (
            await _count(
                admin, "SELECT count(*) FROM events_outbox WHERE household_id = :h", {"h": h}
            )
            == 2
        )
        # For THIS marker: only the recent ledger row survives.
        assert (
            await _count(
                admin, "SELECT count(*) FROM processed_events WHERE handler = :h", {"h": handler}
            )
            == 1
        )
    finally:
        await admin.dispose()
        await maint.dispose()


async def test_reap_spans_households_as_maint(pg: PgDatabase) -> None:
    admin = _engine(pg, pg.username, pg.password)
    maint = _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    h_a, h_b = uuid.uuid4(), uuid.uuid4()
    try:
        await _seed_processed(admin, household_id=h_a, days_ago=40)
        await _seed_processed(admin, household_id=h_b, days_ago=40)

        async with sm() as s:
            await reap(s, retention_days=30)

        # The maint reaper crosses households (RLS maint policy, migration 0004).
        for h in (h_a, h_b):
            assert (
                await _count(
                    admin, "SELECT count(*) FROM events_outbox WHERE household_id = :h", {"h": h}
                )
                == 0
            )
    finally:
        await admin.dispose()
        await maint.dispose()


async def test_drain_processes_due_events_until_idle(pg: PgDatabase) -> None:
    admin = _engine(pg, pg.username, pg.password)
    maint = _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    h = uuid.uuid4()
    try:
        get_dispatcher.cache_clear()  # S1: no handlers registered -> events deliver as no-ops
        # Isolate from earlier tests' leftover (unprocessed) rows in the shared container.
        async with admin.begin() as conn:
            await conn.execute(text("DELETE FROM events_outbox"))
        for _ in range(5):
            await _seed_unprocessed(admin, household_id=h, etype="drain.evt")

        processed = await drain_outbox(sm)
        assert processed == 5
        # A second pass finds nothing due -> the loop terminates on an idle batch.
        assert await drain_outbox(sm) == 0
        # Every seeded event is now marked processed.
        assert (
            await _count(
                admin,
                "SELECT count(*) FROM events_outbox "
                "WHERE household_id = :h AND processed_at IS NULL",
                {"h": h},
            )
            == 0
        )
    finally:
        await admin.dispose()
        await maint.dispose()
