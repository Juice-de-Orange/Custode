"""RLS negative test for the points ledger (Testcontainers PG 18). Household A cannot see B's ledger
rows; WITH CHECK refuses writing a foreign household_id. Skipped without Docker."""

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


async def test_ledger_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, m_a, m_b, user, rew_a, rew_b = (uuid.uuid4() for _ in range(7))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO points_ledger "
            "(household_id, from_account, to_account, amount, ref_type) "
            "VALUES ($1,'system',$2,10,'task_completion'), "
            "($3,'system',$4,5,'task_completion');",
            h_a,
            f"member:{m_a}",
            h_b,
            f"member:{m_b}",
        )
        await su.execute(
            "INSERT INTO rewards (id, household_id, title, cost) "
            "VALUES ($1,$2,'A',10), ($3,$4,'B',20);",
            rew_a,
            h_a,
            rew_b,
            h_b,
        )
        await su.execute(
            "INSERT INTO redemptions (household_id, reward_id, member_id, title, cost) "
            "VALUES ($1,$2,$3,'A',10), ($4,$5,$6,'B',20);",
            h_a,
            rew_a,
            m_a,
            h_b,
            rew_b,
            m_b,
        )
    finally:
        await su.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await app.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false);",
            str(h_a),
            str(user),
        )
        rows = await app.fetch("SELECT amount FROM points_ledger;")
        assert [r["amount"] for r in rows] == [10]
        assert (
            await app.fetchval("SELECT count(*) FROM points_ledger WHERE household_id=$1;", h_b)
            == 0
        )
        assert [r["title"] for r in await app.fetch("SELECT title FROM rewards;")] == ["A"]
        assert [r["title"] for r in await app.fetch("SELECT title FROM redemptions;")] == ["A"]
        assert await app.fetchval("SELECT count(*) FROM rewards WHERE household_id=$1;", h_b) == 0
        # WITH CHECK refuses inserting a foreign-household row while scoped to A (SQLSTATE 42501).
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO points_ledger "
                "(household_id, from_account, to_account, amount, ref_type) "
                "VALUES ($1,'system','member:x',1,'task_completion');",
                h_b,
            )
    finally:
        await app.close()
