"""RLS negative test for guides (Testcontainers PG 18). Household A cannot see B's guides; WITH
CHECK refuses a foreign household_id. Skipped without Docker."""

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


async def test_guides_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO guides (household_id, author_id, title) VALUES ($1,$3,'A'), ($2,$3,'B');",
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
        rows = await app.fetch("SELECT title FROM guides;")
        assert [r["title"] for r in rows] == ["A"]  # B's guide is invisible
        assert await app.fetchval("SELECT count(*) FROM guides WHERE household_id=$1;", h_b) == 0
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO guides (household_id, author_id, title) VALUES ($1,$2,'X');",
                h_b,
                user,
            )
    finally:
        await app.close()


async def test_guide_attachments_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, guide, user = (uuid.uuid4() for _ in range(4))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO guide_attachments "
            "(household_id, guide_id, filename, content_type, byte_size, storage_key, uploaded_by) "
            "VALUES ($1,$3,'a.pdf','application/pdf',1,'k-a',$4), "
            "($2,$3,'b.pdf','application/pdf',1,'k-b',$4);",
            h_a,
            h_b,
            guide,
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
        rows = await app.fetch("SELECT filename FROM guide_attachments;")
        assert [r["filename"] for r in rows] == ["a.pdf"]  # B's attachment is invisible
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO guide_attachments "
                "(household_id, guide_id, filename, content_type, byte_size, storage_key, "
                "uploaded_by) VALUES ($1,$2,'x.pdf','application/pdf',1,'k-x',$3);",
                h_b,
                guide,
                user,
            )
    finally:
        await app.close()
