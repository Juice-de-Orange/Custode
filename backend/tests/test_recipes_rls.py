"""RLS negative tests for recipes (Testcontainers Postgres 18). Proves household isolation: the
app role sees only its active household's recipes + ingredient lines. Migrations are applied via
Alembic so the real 0016 policies are exercised. Skipped when Docker is unavailable."""

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


async def test_recipes_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, r_a, r_b, u = (uuid.uuid4() for _ in range(5))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO recipes (id, household_id, title) "
            "VALUES ($1,$2,'Pasta A'), ($3,$4,'Pasta B');",
            r_a,
            h_a,
            r_b,
            h_b,
        )
        await su.execute(
            "INSERT INTO recipe_ingredients (household_id, recipe_id, raw_text) "
            "VALUES ($1,$2,'500g Mehl'), ($3,$4,'2 Eier');",
            h_a,
            r_a,
            h_b,
            r_b,
        )
    finally:
        await su.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await app.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false);",
            str(h_a),
            str(u),
        )
        assert [r["title"] for r in await app.fetch("SELECT title FROM recipes;")] == ["Pasta A"]
        assert await app.fetchval("SELECT count(*) FROM recipes WHERE household_id = $1;", h_b) == 0
        rows = await app.fetch("SELECT raw_text FROM recipe_ingredients;")
        assert [r["raw_text"] for r in rows] == ["500g Mehl"]
    finally:
        await app.close()

    bare = await _connect(migrated_pg, "custode_app", "app")
    try:
        assert await bare.fetchval("SELECT count(*) FROM recipes;") == 0  # no scope -> 0 rows
        assert await bare.fetchval("SELECT count(*) FROM recipe_ingredients;") == 0
    finally:
        await bare.close()
