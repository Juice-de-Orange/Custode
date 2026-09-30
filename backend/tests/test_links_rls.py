"""RLS negative test for object_links (Testcontainers PG 18). Household A cannot see B's links; WITH
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


async def test_object_links_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user, oa, ob = (uuid.uuid4() for _ in range(5))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO object_links "
            "(household_id, src_type, src_id, dst_type, dst_id, relation, created_by) "
            "VALUES ($1,'guide',$4,'recipe',$5,'related',$3), "
            "($2,'guide',$4,'recipe',$5,'related',$3);",
            h_a,
            h_b,
            user,
            oa,
            ob,
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
        rows = await app.fetch("SELECT household_id FROM object_links;")
        assert [r["household_id"] for r in rows] == [h_a]  # B's link is invisible
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO object_links "
                "(household_id, src_type, src_id, dst_type, dst_id, relation, created_by) "
                "VALUES ($1,'guide',$3,'recipe',$4,'related',$2);",
                h_b,
                user,
                oa,
                ob,
            )
    finally:
        await app.close()
