"""audit_log append-only + isolation (Testcontainers PG 18, ADR-0073). ``ops_actions`` may append +
read; ``ops_readonly`` may read; **nobody** may UPDATE/DELETE (append-only); ``custode_app`` is
locked out (the security log is ops-only). Skipped without Docker."""

from __future__ import annotations

import uuid

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.kernel.audit.record import record_audit
from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


def _maker(container: PgDatabase, role: str, pw: str) -> async_sessionmaker[AsyncSession]:
    host = container.get_container_host_ip()
    port = int(container.get_exposed_port(5432))
    url = f"postgresql+asyncpg://{role}:{pw}@{host}:{port}/{container.dbname}"
    return async_sessionmaker(create_async_engine(url), expire_on_commit=False)


async def test_audit_append_and_read(migrated_pg: PgDatabase) -> None:
    # ops_actions appends via the helper; ops_readonly sees it.
    async with _maker(migrated_pg, "ops_actions", "ops_act")() as session:
        entry = await record_audit(
            session, actor_type="operator", actor_id=uuid.uuid4(), action="banner.created"
        )
        await session.commit()
        entry_id = entry.id

    ro = await _connect(migrated_pg, "ops_readonly", "ops")
    try:
        row = await ro.fetchrow("SELECT action FROM audit_log WHERE id = $1;", entry_id)
        assert row is not None and row["action"] == "banner.created"
    finally:
        await ro.close()


async def test_audit_is_append_only(migrated_pg: PgDatabase) -> None:
    # No role holds UPDATE/DELETE — the security log cannot be rewritten.
    act = await _connect(migrated_pg, "ops_actions", "ops_act")
    try:
        await act.execute("INSERT INTO audit_log (actor_type, action) VALUES ('system','x');")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await act.execute("UPDATE audit_log SET action = 'y';")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await act.execute("DELETE FROM audit_log;")
    finally:
        await act.close()


async def test_audit_hidden_from_app(migrated_pg: PgDatabase) -> None:
    # The household app role must not read or write the ops/security log.
    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute("SELECT * FROM audit_log;")
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute("INSERT INTO audit_log (actor_type, action) VALUES ('user','x');")
    finally:
        await app.close()
