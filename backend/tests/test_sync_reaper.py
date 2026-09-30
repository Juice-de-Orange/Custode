"""Reaper test for ``sync_client_ops`` (Testcontainers PG 18). ``custode_maint`` deletes idempotency
markers older than the retention window across households (maint_all policy, migration 0021);
recent markers stay. Skipped without Docker."""

from __future__ import annotations

import uuid

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.kernel.sync.reaper import reap_sync_ops
from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_reaper_drops_old_markers_across_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b = uuid.uuid4(), uuid.uuid4()
    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO sync_client_ops (household_id, client_op_id, created_at) "
            "VALUES ($1,$2, now() - interval '60 days'), ($3,$4, now());",
            h_a,
            uuid.uuid4(),
            h_b,
            uuid.uuid4(),
        )
    finally:
        await su.close()

    host = migrated_pg.get_container_host_ip()
    port = int(migrated_pg.get_exposed_port(5432))
    engine = create_async_engine(
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{migrated_pg.dbname}"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            removed = await reap_sync_ops(session, retention_days=30)
    finally:
        await engine.dispose()

    assert removed == 1  # only the 60-day-old marker (maint spans both households)

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        assert (
            await su.fetchval("SELECT count(*) FROM sync_client_ops;") == 1
        )  # the fresh one stays
    finally:
        await su.close()
