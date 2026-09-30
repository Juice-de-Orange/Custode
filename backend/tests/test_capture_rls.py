"""RLS negative test for captures (Testcontainers PG 18). Household A cannot see B's captures;
WITH CHECK refuses a foreign household_id. Skipped without Docker."""

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


async def test_captures_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, member_a, member_b, user = (uuid.uuid4() for _ in range(5))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO captures (household_id, member_id, raw_text) "
            "VALUES ($1,$2,'Milch kaufen'), ($3,$4,'Brot holen');",
            h_a,
            member_a,
            h_b,
            member_b,
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
        assert [r["raw_text"] for r in await app.fetch("SELECT raw_text FROM captures;")] == [
            "Milch kaufen"
        ]
        assert await app.fetchval("SELECT count(*) FROM captures WHERE household_id=$1;", h_b) == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO captures (household_id, member_id, raw_text) VALUES ($1,$2,'X');",
                h_b,
                member_b,
            )
    finally:
        await app.close()
