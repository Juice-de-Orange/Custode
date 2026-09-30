"""RLS negative test for weather_locations (Testcontainers PG 18). Household A cannot see B's
location; WITH CHECK refuses a foreign household_id. Skipped without Docker."""

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


async def test_weather_locations_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO weather_locations (household_id, lat, lon, label) "
            "VALUES ($1, 48.2, 16.37, 'A'), ($2, 51.5, -0.12, 'B');",
            h_a,
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
        assert [r["label"] for r in await app.fetch("SELECT label FROM weather_locations;")] == [
            "A"
        ]
        assert (
            await app.fetchval("SELECT count(*) FROM weather_locations WHERE household_id=$1;", h_b)
            == 0
        )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO weather_locations (household_id, lat, lon) VALUES ($1, 0, 0);",
                h_b,
            )
    finally:
        await app.close()
