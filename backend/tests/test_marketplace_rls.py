"""RLS negative test for market_listings (Testcontainers PG 18). Household A cannot see B's
listings; WITH CHECK refuses a foreign household_id. Skipped without Docker."""

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


async def test_marketplace_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, inst_a, inst_b, seller, user = (uuid.uuid4() for _ in range(6))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO market_listings "
            "(household_id, task_instance_id, title, seller_id, price) "
            "VALUES ($1,$2,'A',$3,10), ($4,$5,'B',$6,20);",
            h_a,
            inst_a,
            seller,
            h_b,
            inst_b,
            seller,
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
        assert [r["price"] for r in await app.fetch("SELECT price FROM market_listings;")] == [10]
        assert (
            await app.fetchval("SELECT count(*) FROM market_listings WHERE household_id=$1;", h_b)
            == 0
        )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO market_listings "
                "(household_id, task_instance_id, title, seller_id, price) "
                "VALUES ($1,$2,'X',$3,1);",
                h_b,
                inst_b,
                seller,
            )
    finally:
        await app.close()
