"""RLS negative test for comments (Testcontainers PG 18). Household A cannot see B's comments; WITH
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


async def test_comments_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user, obj = (uuid.uuid4() for _ in range(4))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO comments (household_id, object_type, object_id, author_id, body_md) "
            "VALUES ($1,'guide',$4,$3,'A'), ($2,'guide',$4,$3,'B');",
            h_a,
            h_b,
            user,
            obj,
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
        rows = await app.fetch("SELECT body_md FROM comments;")
        assert [r["body_md"] for r in rows] == ["A"]  # B's comment is invisible
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO comments (household_id, object_type, object_id, author_id, body_md) "
                "VALUES ($1,'guide',$3,$2,'X');",
                h_b,
                user,
                obj,
            )
    finally:
        await app.close()
