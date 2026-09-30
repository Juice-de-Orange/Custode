"""RLS negative tests for accounts (Testcontainers Postgres 18). Proves tenant
isolation: the app role sees only its active household's rows, and in the global
``users`` table only itself + co-members. Migrations are applied via Alembic so
the real 0002 policies are exercised. Skipped when Docker is unavailable."""

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


async def test_accounts_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    h_a, h_b = uuid.uuid4(), uuid.uuid4()

    # Seed as superuser (bypasses RLS).
    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO users (id, display_name) VALUES ($1, 'A'), ($2, 'B');", u1, u2
        )
        await su.execute(
            "INSERT INTO households (id, name) VALUES ($1, 'HA'), ($2, 'HB');", h_a, h_b
        )
        await su.execute(
            "INSERT INTO memberships (household_id, user_id, role) "
            "VALUES ($1, $2, 'admin'), ($3, $4, 'admin');",
            h_a,
            u1,
            h_b,
            u2,
        )
    finally:
        await su.close()

    app = await _connect(migrated_pg, "custode_app", "app")
    try:

        async def scope(hid: uuid.UUID, uid: uuid.UUID) -> None:
            await app.execute(
                "SELECT set_config('app.household_id', $1, false), "
                "set_config('app.user_id', $2, false);",
                str(hid),
                str(uid),
            )

        await scope(h_a, u1)
        assert [r["name"] for r in await app.fetch("SELECT name FROM households;")] == ["HA"]
        assert await app.fetchval("SELECT count(*) FROM memberships;") == 1
        # users: self + co-members of HA -> only A
        assert await app.fetchval("SELECT display_name FROM users;") == "A"
        assert await app.fetchval("SELECT count(*) FROM households WHERE name = 'HB';") == 0

        await scope(h_b, u2)
        assert [r["name"] for r in await app.fetch("SELECT name FROM households;")] == ["HB"]
        assert await app.fetchval("SELECT display_name FROM users;") == "B"
    finally:
        await app.close()

    # Fresh connection without any scope -> NULL setting -> zero rows everywhere.
    bare = await _connect(migrated_pg, "custode_app", "app")
    try:
        assert await bare.fetchval("SELECT count(*) FROM households;") == 0
        assert await bare.fetchval("SELECT count(*) FROM memberships;") == 0
        assert await bare.fetchval("SELECT count(*) FROM users;") == 0
    finally:
        await bare.close()


async def test_consents_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, u = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO consents (household_id, subject_user_id, type, granted_by) "
            "VALUES ($1, $2, 'wearables', $2), ($3, $2, 'wearables', $2);",
            h_a,
            u,
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
            str(u),
        )
        rows = await app.fetch("SELECT household_id FROM consents;")
        assert [r["household_id"] for r in rows] == [h_a]  # only the active household's consent
        assert (
            await app.fetchval("SELECT count(*) FROM consents WHERE household_id = $1;", h_b) == 0
        )
    finally:
        await app.close()

    bare = await _connect(migrated_pg, "custode_app", "app")
    try:
        assert await bare.fetchval("SELECT count(*) FROM consents;") == 0  # no scope -> 0 rows
    finally:
        await bare.close()
