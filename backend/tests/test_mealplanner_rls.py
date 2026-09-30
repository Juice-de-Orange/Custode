"""RLS negative test for meal_plans + meal_slots (Testcontainers PG 18). Household A cannot see B's
plan/slots; WITH CHECK refuses a foreign household_id. Skipped without Docker."""

from __future__ import annotations

import uuid
from datetime import date

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


async def test_meal_plans_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))
    monday = date(2026, 6, 22)

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO meal_plans (household_id, week_start) VALUES ($1,$3), ($2,$3);",
            h_a,
            h_b,
            monday,
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
        assert await app.fetchval("SELECT count(*) FROM meal_plans;") == 1
        assert (
            await app.fetchval("SELECT count(*) FROM meal_plans WHERE household_id=$1;", h_b) == 0
        )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO meal_plans (household_id, week_start) VALUES ($1,$2);", h_b, monday
            )
    finally:
        await app.close()


async def test_meal_slots_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))
    monday = date(2026, 7, 6)

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        plan_a = await su.fetchval(
            "INSERT INTO meal_plans (household_id, week_start) VALUES ($1,$2) RETURNING id;",
            h_a,
            monday,
        )
        plan_b = await su.fetchval(
            "INSERT INTO meal_plans (household_id, week_start) VALUES ($1,$2) RETURNING id;",
            h_b,
            monday,
        )
        await su.execute(
            "INSERT INTO meal_slots (household_id, plan_id, day_of_week, slot, free_text) "
            "VALUES ($1,$2,0,'dinner','A'), ($3,$4,0,'dinner','B');",
            h_a,
            plan_a,
            h_b,
            plan_b,
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
        rows = await app.fetch("SELECT free_text FROM meal_slots;")
        assert [r["free_text"] for r in rows] == ["A"]
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO meal_slots (household_id, plan_id, day_of_week, slot) "
                "VALUES ($1,$2,1,'lunch');",
                h_b,
                plan_b,
            )
    finally:
        await app.close()
