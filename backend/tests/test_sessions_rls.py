"""RLS test for auth_sessions (Testcontainers Postgres 18): a user sees only their
own sessions (``user_id = app.user_id``), zero without a scope; ``custode_maint``
sees all (the cross-user refresh lookup). Skipped without Docker."""

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


async def test_auth_sessions_rls_isolates_users(migrated_pg: PgDatabase) -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO users (id, display_name) VALUES ($1, 'A'), ($2, 'B');", u1, u2
        )
        await su.execute(
            "INSERT INTO auth_sessions (user_id, family_id, refresh_hash, expires_at) "
            "VALUES ($1, $2, 'hash-a', now() + interval '30 days'), "
            "       ($3, $4, 'hash-b', now() + interval '30 days');",
            u1,
            uuid.uuid4(),
            u2,
            uuid.uuid4(),
        )
    finally:
        await su.close()

    # custode_app scoped to u1 -> only u1's session
    app = await _connect(migrated_pg, "custode_app", "app")
    try:
        await app.execute("SELECT set_config('app.user_id', $1, false);", str(u1))
        assert await app.fetchval("SELECT count(*) FROM auth_sessions;") == 1
        assert await app.fetchval("SELECT user_id FROM auth_sessions;") == u1
    finally:
        await app.close()

    # no scope -> NULL setting -> zero rows
    bare = await _connect(migrated_pg, "custode_app", "app")
    try:
        assert await bare.fetchval("SELECT count(*) FROM auth_sessions;") == 0
    finally:
        await bare.close()

    # custode_maint -> all sessions (cross-user refresh lookup)
    maint = await _connect(migrated_pg, "custode_maint", "maint")
    try:
        assert await maint.fetchval("SELECT count(*) FROM auth_sessions;") == 2
    finally:
        await maint.close()
