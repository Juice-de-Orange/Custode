"""RLS negative test for feedback (Testcontainers PG 18). Household A cannot see B's feedback; WITH
CHECK refuses a foreign household_id. Skipped without Docker."""

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


async def test_feedback_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO feedback (household_id, author_id, category, message) "
            "VALUES ($1,$3,'bug','A'), ($2,$3,'idea','B');",
            h_a,
            h_b,
            user,
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
        rows = await app.fetch("SELECT message FROM feedback;")
        assert [r["message"] for r in rows] == ["A"]  # B's feedback is invisible
        assert await app.fetchval("SELECT count(*) FROM feedback WHERE household_id=$1;", h_b) == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO feedback (household_id, author_id, category, message) "
                "VALUES ($1,$2,'bug','X');",
                h_b,
                user,
            )
    finally:
        await app.close()
