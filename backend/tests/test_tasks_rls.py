"""RLS negative tests for tasks (Testcontainers PG 18). Household A cannot see B's templates or
instances; WITH CHECK refuses writing a foreign household_id. Skipped without Docker."""

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


async def test_tasks_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, tmpl_a, tmpl_b, inst_a, inst_b, user, room_a, room_b = (
        uuid.uuid4() for _ in range(9)
    )

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO rooms (id, household_id, name, decay_days) "
            "VALUES ($1,$2,'A',7), ($3,$4,'B',7);",
            room_a,
            h_a,
            room_b,
            h_b,
        )
        await su.execute(
            "INSERT INTO task_templates (id, household_id, title, points) "
            "VALUES ($1,$2,'A',5), ($3,$4,'B',5);",
            tmpl_a,
            h_a,
            tmpl_b,
            h_b,
        )
        await su.execute(
            "INSERT INTO task_instances (id, household_id, template_id, title) "
            "VALUES ($1,$2,$3,'A'), ($4,$5,$6,'B');",
            inst_a,
            h_a,
            tmpl_a,
            inst_b,
            h_b,
            tmpl_b,
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
        assert [r["title"] for r in await app.fetch("SELECT title FROM task_templates;")] == ["A"]
        assert [r["title"] for r in await app.fetch("SELECT title FROM task_instances;")] == ["A"]
        assert [r["name"] for r in await app.fetch("SELECT name FROM rooms;")] == ["A"]
        assert (
            await app.fetchval("SELECT count(*) FROM task_instances WHERE household_id=$1;", h_b)
            == 0
        )
        # WITH CHECK: writing a row for a foreign household (while scoped to A) is refused by the
        # RLS policy (SQLSTATE 42501 -> InsufficientPrivilegeError), not a CHECK constraint.
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO task_templates (household_id, title) VALUES ($1,'X');", h_b
            )
    finally:
        await app.close()
