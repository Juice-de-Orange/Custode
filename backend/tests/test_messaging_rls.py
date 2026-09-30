"""RLS negative test for letters + letter_reads (Testcontainers PG 18). Household A cannot see B's
letters/reads; WITH CHECK refuses a foreign household_id. Skipped without Docker."""

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


async def test_letters_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        letter_a = await su.fetchval(
            "INSERT INTO letters (household_id, from_id, subject) VALUES ($1,$2,'A') RETURNING id;",
            h_a,
            user,
        )
        await su.execute(
            "INSERT INTO letters (household_id, from_id, subject) VALUES ($1,$2,'B');",
            h_b,
            user,
        )
        await su.execute(
            "INSERT INTO letter_reads (household_id, letter_id, user_id) VALUES ($1,$2,$3);",
            h_a,
            letter_a,
            user,
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
        rows = await app.fetch("SELECT subject FROM letters;")
        assert [r["subject"] for r in rows] == ["A"]  # B's letter is invisible
        assert await app.fetchval("SELECT count(*) FROM letter_reads;") == 1
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO letters (household_id, from_id, subject) VALUES ($1,$2,'X');",
                h_b,
                user,
            )
    finally:
        await app.close()
