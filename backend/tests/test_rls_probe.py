"""RLS negative test (ARCHITECTURE §9, ENTWICKLUNGSKONZEPT Teil E). Proves the
isolation machinery end-to-end against a real Postgres 18 (Testcontainers):
the app role (NOBYPASSRLS, not owner) sees only its own household's rows, and
nothing without a household context. Skipped when Docker is unavailable."""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("testcontainers.postgres")

import asyncpg
from testcontainers.postgres import PostgresContainer

PROBE_DDL = """
CREATE TABLE tenancy_probe (
    id uuid PRIMARY KEY DEFAULT uuidv7(),
    household_id uuid NOT NULL,
    label text NOT NULL DEFAULT ''
);
ALTER TABLE tenancy_probe ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenancy_probe FORCE ROW LEVEL SECURITY;
CREATE POLICY household_isolation ON tenancy_probe
    USING (household_id = current_setting('app.household_id', true)::uuid)
    WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);
GRANT SELECT, INSERT, UPDATE, DELETE ON tenancy_probe TO custode_app;
"""


@pytest.fixture(scope="module")
def pg():
    try:
        container = PostgresContainer("postgres:18")
        container.start()
    except Exception as exc:  # Docker not available (e.g. local without Docker)
        pytest.skip(f"Docker/Postgres not available: {exc}")
    try:
        yield container
    finally:
        container.stop()


async def _connect(container: PostgresContainer, user: str, password: str):
    return await asyncpg.connect(
        host=container.get_container_host_ip(),
        port=int(container.get_exposed_port(5432)),
        user=user,
        password=password,
        database=container.dbname,
    )


async def test_rls_isolates_households(pg: PostgresContainer) -> None:
    admin = await _connect(pg, pg.username, pg.password)
    hh_a, hh_b = uuid.uuid4(), uuid.uuid4()
    try:
        await admin.execute("CREATE ROLE custode_app LOGIN PASSWORD 'app' NOSUPERUSER NOBYPASSRLS;")
        await admin.execute("GRANT USAGE ON SCHEMA public TO custode_app;")
        await admin.execute(PROBE_DDL)
        # superuser bypasses RLS -> seed both tenants
        await admin.execute(
            "INSERT INTO tenancy_probe (household_id, label) VALUES ($1, 'a'), ($2, 'b');",
            hh_a,
            hh_b,
        )
    finally:
        await admin.close()

    app_conn = await _connect(pg, "custode_app", "app")
    try:
        # No household context -> zero rows (the core isolation guarantee).
        assert await app_conn.fetchval("SELECT count(*) FROM tenancy_probe;") == 0
        # Household A sees only A.
        await app_conn.execute("SELECT set_config('app.household_id', $1, false);", str(hh_a))
        assert [r["label"] for r in await app_conn.fetch("SELECT label FROM tenancy_probe;")] == [
            "a"
        ]
        # Household B sees only B.
        await app_conn.execute("SELECT set_config('app.household_id', $1, false);", str(hh_b))
        assert [r["label"] for r in await app_conn.fetch("SELECT label FROM tenancy_probe;")] == [
            "b"
        ]
    finally:
        await app_conn.close()
