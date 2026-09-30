"""Ops-Console DB isolation (Testcontainers PG 18, ADR-0015/0071). ``ops_readonly`` may read the
**aggregate views** (KPIs) but must NOT read any fact table — the views are security-definer, owned
by ``custode_maint``, so they aggregate across households while the ops role holds no fact-table
grant. Skipped without Docker."""

from __future__ import annotations

import uuid

import asyncpg
import pytest

from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_ops_reads_aggregates_not_fact_tables(migrated_pg: PgDatabase) -> None:
    hh, user = uuid.uuid4(), uuid.uuid4()
    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute("INSERT INTO households (id, name) VALUES ($1,'Familie');", hh)
        await su.execute(
            "INSERT INTO users (id, display_name, email) VALUES ($1,'A','a@example.de');", user
        )
        await su.execute(
            "INSERT INTO memberships (household_id, user_id, role) VALUES ($1,$2,'admin');",
            hh,
            user,
        )
    finally:
        await su.close()

    ops = await _connect(migrated_pg, "ops_readonly", "ops")
    try:
        # Aggregates are readable and correct (the security-definer view sees all households).
        counters = await ops.fetchrow("SELECT * FROM usage_counters;")
        assert counters["households"] == 1
        assert counters["users"] == 1
        assert counters["adult_members"] == 1
        assert counters["children"] == 0
        days = await ops.fetch("SELECT * FROM daily_metrics;")
        assert sum(d["new_households"] for d in days) == 1
        assert sum(d["new_users"] for d in days) == 1

        # Fact tables are NOT readable: ops holds no grant on them.
        for table in ("households", "users", "memberships"):
            with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
                await ops.execute(f"SELECT * FROM {table};")  # noqa: S608 - literal table names
    finally:
        await ops.close()


async def test_operators_table_credentials_hidden_from_app(migrated_pg: PgDatabase) -> None:
    # ops_readonly may read operators (login lookups); the regular app role may NOT — operator
    # credentials must never be reachable from the household app (migration 0056 revokes it).
    ops = await _connect(migrated_pg, "ops_readonly", "ops")
    try:
        assert await ops.fetchval("SELECT count(*) FROM operators;") == 0
    finally:
        await ops.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute("SELECT * FROM operators;")
    finally:
        await app.close()
