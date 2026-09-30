"""Outbox dispatcher integration tests (Testcontainers Postgres 18): idempotency,
exponential-backoff retry, dead-lettering, and cross-household delivery as
``custode_maint`` (RLS maint policy from migration 0004). Skipped without Docker."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.kernel.events.dispatcher import OutboxDispatcher
from app.kernel.events.envelope import EventEnvelope
from conftest import PgDatabase


def _engine(pg: PgDatabase, user: str, password: str) -> AsyncEngine:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    return create_async_engine(f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{pg.dbname}")


async def _seed(admin: AsyncEngine, *, household_id: uuid.UUID, etype: str) -> uuid.UUID:
    # Superuser bypasses RLS — seed directly.
    async with admin.begin() as conn:
        return await conn.scalar(  # type: ignore[return-value]
            text(
                "INSERT INTO events_outbox (type, household_id, payload) "
                "VALUES (:t, :h, '{}'::jsonb) RETURNING id"
            ),
            {"t": etype, "h": household_id},
        )


async def _row(admin: AsyncEngine, eid: uuid.UUID) -> dict:
    async with admin.connect() as conn:
        return dict(
            (
                await conn.execute(
                    text(
                        "SELECT attempts, processed_at, last_error "
                        "FROM events_outbox WHERE id = :id"
                    ),
                    {"id": eid},
                )
            )
            .mappings()
            .one()
        )


def _counter(calls: list[uuid.UUID]) -> Callable:
    async def handler(env: EventEnvelope) -> None:
        calls.append(env.household_id)

    return handler


def _flaky(calls: list[uuid.UUID], fail_first: int) -> Callable:
    state = {"n": 0}

    async def handler(env: EventEnvelope) -> None:
        calls.append(env.household_id)
        state["n"] += 1
        if state["n"] <= fail_first:
            raise RuntimeError("transient boom")

    return handler


async def test_dispatch_success_then_idle(pg: PgDatabase) -> None:
    admin, maint = _engine(pg, pg.username, pg.password), _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    try:
        h = uuid.uuid4()
        eid = await _seed(admin, household_id=h, etype="ok.evt")
        calls: list[uuid.UUID] = []
        disp = OutboxDispatcher(max_attempts=3, base_backoff_s=0.0)
        disp.register("ok.evt", "counter", _counter(calls))

        async with sm() as s:
            res = await disp.dispatch_once(s)
        assert (res.processed, res.retried, res.dead_lettered) == (1, 0, 0)
        assert calls == [h]
        assert (await _row(admin, eid))["processed_at"] is not None

        # Nothing due on a second pass; handler is not re-run.
        async with sm() as s:
            res2 = await disp.dispatch_once(s)
        assert res2.total == 0
        assert calls == [h]
    finally:
        await admin.dispose()
        await maint.dispose()


async def test_idempotent_partial_failure(pg: PgDatabase) -> None:
    """Handler A succeeds, B fails once then succeeds. On retry A must NOT re-run."""
    admin, maint = _engine(pg, pg.username, pg.password), _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    try:
        h = uuid.uuid4()
        await _seed(admin, household_id=h, etype="multi.evt")
        a_calls: list[uuid.UUID] = []
        b_calls: list[uuid.UUID] = []
        disp = OutboxDispatcher(max_attempts=5, base_backoff_s=0.0)
        disp.register("multi.evt", "A", _counter(a_calls))
        disp.register("multi.evt", "B", _flaky(b_calls, fail_first=1))

        async with sm() as s:
            r1 = await disp.dispatch_once(s)
        assert (r1.processed, r1.retried) == (0, 1)  # B failed -> retried
        assert len(a_calls) == 1 and len(b_calls) == 1

        async with sm() as s:
            r2 = await disp.dispatch_once(s)
        assert r2.processed == 1  # B now succeeds -> event done
        assert len(a_calls) == 1  # A was skipped via ledger (idempotent!)
        assert len(b_calls) == 2
    finally:
        await admin.dispose()
        await maint.dispose()


async def test_retry_then_dead_letter(pg: PgDatabase) -> None:
    admin, maint = _engine(pg, pg.username, pg.password), _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    try:
        h = uuid.uuid4()
        eid = await _seed(admin, household_id=h, etype="bad.evt")
        disp = OutboxDispatcher(max_attempts=3, base_backoff_s=0.0)
        disp.register("bad.evt", "always_fails", _flaky([], fail_first=99))

        outcomes = []
        for _ in range(3):
            async with sm() as s:
                outcomes.append(await disp.dispatch_once(s))
        assert [o.retried for o in outcomes] == [1, 1, 0]
        assert outcomes[2].dead_lettered == 1

        row = await _row(admin, eid)
        assert row["attempts"] == 3
        assert row["processed_at"] is not None  # removed from the active queue
        async with admin.connect() as conn:
            dlq = await conn.scalar(
                text("SELECT count(*) FROM events_dlq WHERE event_id = :e"), {"e": eid}
            )
        assert dlq == 1
    finally:
        await admin.dispose()
        await maint.dispose()


async def test_cross_household_delivery(pg: PgDatabase) -> None:
    """The maint dispatcher processes events from every household (RLS maint policy)."""
    admin, maint = _engine(pg, pg.username, pg.password), _engine(pg, "custode_maint", "maint")
    sm = async_sessionmaker(maint, expire_on_commit=False)
    try:
        h_a, h_b = uuid.uuid4(), uuid.uuid4()
        await _seed(admin, household_id=h_a, etype="xh.evt")
        await _seed(admin, household_id=h_b, etype="xh.evt")
        calls: list[uuid.UUID] = []
        disp = OutboxDispatcher(max_attempts=3, base_backoff_s=0.0)
        disp.register("xh.evt", "counter", _counter(calls))

        async with sm() as s:
            res = await disp.dispatch_once(s)
        assert res.processed == 2
        assert set(calls) == {h_a, h_b}
    finally:
        await admin.dispose()
        await maint.dispose()
