"""RLS negative test for notes (Testcontainers PG 18). Household A cannot see B's notes; WITH CHECK
refuses a foreign household_id. Skipped without Docker."""

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


async def test_notes_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO notes (household_id, author_id, title) VALUES ($1,$3,'A'), ($2,$3,'B');",
            h_a,
            h_b,
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
        rows = await app.fetch("SELECT title FROM notes;")
        assert [r["title"] for r in rows] == ["A"]  # B's note is invisible
        assert await app.fetchval("SELECT count(*) FROM notes WHERE household_id=$1;", h_b) == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO notes (household_id, author_id, title) VALUES ($1,$2,'X');",
                h_b,
                user,
            )
    finally:
        await app.close()


async def test_note_versions_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        note_a = await su.fetchval(
            "INSERT INTO notes (household_id, author_id, title) VALUES ($1,$2,'A') RETURNING id;",
            h_a,
            user,
        )
        note_b = await su.fetchval(
            "INSERT INTO notes (household_id, author_id, title) VALUES ($1,$2,'B') RETURNING id;",
            h_b,
            user,
        )
        await su.execute(
            "INSERT INTO note_versions "
            "(household_id, note_id, version_no, title, body_md, edited_by) "
            "VALUES ($1,$2,1,'A','',$5), ($3,$4,1,'B','',$5);",
            h_a,
            note_a,
            h_b,
            note_b,
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
        rows = await app.fetch("SELECT title FROM note_versions;")
        assert [r["title"] for r in rows] == ["A"]  # B's version snapshot is invisible
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO note_versions "
                "(household_id, note_id, version_no, title, body_md, edited_by) "
                "VALUES ($1,$2,2,'X','',$3);",
                h_b,
                note_b,
                user,
            )
    finally:
        await app.close()
