"""RLS negative test for the event tables (Testcontainers Postgres 18). Proves
``events_outbox``/``events_dlq`` are household-isolated: the app role sees only
its active household's events, and zero rows without a scope. Migrations run via
Alembic so the real 0003 policies are exercised. Skipped when Docker is absent."""

from __future__ import annotations

import uuid

import asyncpg

from conftest import PgDatabase


async def _connect(container: PgDatabase, user: str, password: str):
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_events_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b = uuid.uuid4(), uuid.uuid4()

    # Seed events for two households as superuser (bypasses RLS).
    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO events_outbox (type, household_id, payload) "
            "VALUES ('recipe.created', $1, '{}'::jsonb), ('recipe.created', $2, '{}'::jsonb);",
            h_a,
            h_b,
        )
        await su.execute(
            "INSERT INTO events_dlq (event_id, type, household_id, payload, attempts) "
            "VALUES ($1, 'recipe.created', $2, '{}'::jsonb, 5), "
            "       ($3, 'recipe.created', $4, '{}'::jsonb, 5);",
            uuid.uuid4(),
            h_a,
            uuid.uuid4(),
            h_b,
        )
    finally:
        await su.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:

        async def scope(hid: uuid.UUID) -> None:
            await app.execute("SELECT set_config('app.household_id', $1, false);", str(hid))

        await scope(h_a)
        assert await app.fetchval("SELECT count(*) FROM events_outbox;") == 1
        assert await app.fetchval("SELECT count(*) FROM events_dlq;") == 1
        assert await app.fetchval("SELECT household_id FROM events_outbox;") == h_a
        assert (
            await app.fetchval("SELECT count(*) FROM events_outbox WHERE household_id = $1;", h_b)
            == 0
        )

        await scope(h_b)
        assert await app.fetchval("SELECT household_id FROM events_outbox;") == h_b
    finally:
        await app.close()

    # Fresh connection without any scope -> NULL setting -> zero rows everywhere.
    bare = await _connect(migrated_pg, "custode_app", "app")
    try:
        assert await bare.fetchval("SELECT count(*) FROM events_outbox;") == 0
        assert await bare.fetchval("SELECT count(*) FROM events_dlq;") == 0
    finally:
        await bare.close()
