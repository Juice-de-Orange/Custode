"""Reaper test for the retention hard-delete (Testcontainers PG 18, ARCHITECTURE §9).
``custode_maint`` purges tombstoned ``notes`` (``deleted_at`` older than the window) across
households (``maint_all`` policy, migration 0053); newer tombstones and live rows stay. The old
note's ``note_versions`` snapshot cascades via FK ``ON DELETE CASCADE``. Skipped without Docker."""

from __future__ import annotations

import uuid

import asyncpg
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.kernel.retention.reaper import reap_deleted
from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_reaper_purges_old_tombstones_across_households(
    migrated_pg: PgDatabase,
) -> None:
    h_a, h_b = uuid.uuid4(), uuid.uuid4()
    old_a = uuid.uuid4()  # household A, deleted 31d ago -> reaped (+ its version cascades)
    recent_a = uuid.uuid4()  # household A, deleted 29d ago -> kept
    live_a = uuid.uuid4()  # household A, never deleted -> kept
    old_b = uuid.uuid4()  # household B, deleted 31d ago -> reaped (maint spans households)

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO notes (id, household_id, author_id, title, deleted_at) VALUES "
            "($1,$2, $3,'old',   now() - interval '31 days'),"
            "($4,$5, $6,'recent',now() - interval '29 days'),"
            "($7,$8, $9,'live',  NULL),"
            "($10,$11,$12,'old-b',now() - interval '31 days');",
            old_a,
            h_a,
            uuid.uuid4(),
            recent_a,
            h_a,
            uuid.uuid4(),
            live_a,
            h_a,
            uuid.uuid4(),
            old_b,
            h_b,
            uuid.uuid4(),
        )
        # A version snapshot of the old note — must vanish with it via ON DELETE CASCADE.
        await su.execute(
            "INSERT INTO note_versions "
            "(household_id, note_id, version_no, title, body_md, edited_by) "
            "VALUES ($1,$2,1,'old','was here',$3);",
            h_a,
            old_a,
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
            result = await reap_deleted(session, retention_days=30, tables=("notes",))
    finally:
        await engine.dispose()

    # Both 31d tombstones go (households A and B): maint spans households. 29d + live stay.
    assert result.removed == {"notes": 2}
    assert result.total == 2

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        remaining = {r["id"] for r in await su.fetch("SELECT id FROM notes;")}
        assert remaining == {recent_a, live_a}
        # Cascade: the old note's version snapshot is gone; no orphan left behind.
        assert await su.fetchval("SELECT count(*) FROM note_versions;") == 0
    finally:
        await su.close()


async def test_a_failing_table_does_not_take_the_others_down(
    migrated_pg: PgDatabase,
) -> None:
    """Die zweite Hälfte des Fixes von BUGLOG 2026-07-31.

    Der Reaper lief in EINER Transaktion über alle Tabellen. Als zwei Tabellen ohne die nötigen
    maint-Rechte in die Liste wanderten, starb der Job jede Nacht — und nahm den ``notes``-Purge
    mit, der für sich genommen tadellos funktioniert hätte. Ein Teil-Purge ist eine Verzögerung;
    ein Total-Ausfall ist ein gebrochenes Versprechen gegenüber jedem, der seinen Papierkorb
    geleert hat.

    Hier steht eine Tabelle in der Liste, auf die ``custode_maint`` kein Recht hat. Erwartung:
    ``notes`` wird trotzdem geleert, die andere Tabelle erscheint in ``failed``.
    """
    h = uuid.uuid4()
    old = uuid.uuid4()
    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute("TRUNCATE notes CASCADE;")
        await su.execute(
            "INSERT INTO notes (id, household_id, author_id, title, body_md, deleted_at) "
            "VALUES ($1,$2,$3,'alt','x', now() - interval '31 days');",
            old,
            h,
            uuid.uuid4(),
        )
        # operators ist für custode_maint gesperrt (REVOKE ALL, Migration 0056) und hat kein
        # deleted_at — ein realistischer Stellvertreter für "Tabelle, die der Job nicht darf".
    finally:
        await su.close()

    host = migrated_pg.get_container_host_ip()
    port = int(migrated_pg.get_exposed_port(5432))
    engine = create_async_engine(
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{migrated_pg.dbname}"
    )
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            result = await reap_deleted(session, retention_days=30, tables=("operators", "notes"))
    finally:
        await engine.dispose()

    assert "operators" in result.failed
    assert result.removed["notes"] == 1, "notes muss trotz der gescheiterten Tabelle geleert werden"

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        assert await su.fetchval("SELECT count(*) FROM notes;") == 0
    finally:
        await su.close()
