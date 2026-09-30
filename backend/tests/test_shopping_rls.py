"""RLS negative tests for shopping (Testcontainers PG 18). Household A cannot see B's lists, items,
or sync ops. Skipped without Docker."""

from __future__ import annotations

import uuid

import asyncpg

from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_shopping_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, list_a, list_b, item_a, item_b, basic_a, basic_b, user = (
        uuid.uuid4() for _ in range(9)
    )

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO shopping_lists (id, household_id, name) VALUES ($1,$2,'A'), ($3,$4,'B');",
            list_a,
            h_a,
            list_b,
            h_b,
        )
        await su.execute(
            "INSERT INTO shopping_items (id, household_id, list_id, label) "
            "VALUES ($1,$2,$3,'Milch'), ($4,$5,$6,'Brot');",
            item_a,
            h_a,
            list_a,
            item_b,
            h_b,
            list_b,
        )
        await su.execute(
            "INSERT INTO sync_client_ops (household_id, client_op_id) VALUES ($1,$2), ($3,$4);",
            h_a,
            uuid.uuid4(),
            h_b,
            uuid.uuid4(),
        )
        await su.execute(
            "INSERT INTO shopping_basics (id, household_id, label) "
            "VALUES ($1,$2,'Eier'), ($3,$4,'Mehl');",
            basic_a,
            h_a,
            basic_b,
            h_b,
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
        assert [r["name"] for r in await app.fetch("SELECT name FROM shopping_lists;")] == ["A"]
        assert [r["label"] for r in await app.fetch("SELECT label FROM shopping_items;")] == [
            "Milch"
        ]
        assert await app.fetchval("SELECT count(*) FROM sync_client_ops;") == 1
        assert [r["label"] for r in await app.fetch("SELECT label FROM shopping_basics;")] == [
            "Eier"
        ]
        assert (
            await app.fetchval("SELECT count(*) FROM shopping_items WHERE household_id=$1;", h_b)
            == 0
        )
    finally:
        await app.close()
