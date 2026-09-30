"""RLS negative test for calendar_events (Testcontainers PG 18). Household A cannot see B's events;
WITH CHECK refuses a foreign household_id. Skipped without Docker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

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


async def test_calendar_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, owner_a, owner_b, user = (uuid.uuid4() for _ in range(5))
    t0 = datetime(2026, 7, 1, 9, 0, tzinfo=UTC)  # timestamptz: asyncpg needs a datetime, not a str
    t1 = datetime(2026, 7, 1, 10, 0, tzinfo=UTC)

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO calendar_events "
            "(household_id, owner_id, title, starts_at, ends_at) "
            "VALUES ($1,$2,'A',$5,$6), ($3,$4,'B',$5,$6);",
            h_a,
            owner_a,
            h_b,
            owner_b,
            t0,
            t1,
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
        assert [r["title"] for r in await app.fetch("SELECT title FROM calendar_events;")] == ["A"]
        assert (
            await app.fetchval("SELECT count(*) FROM calendar_events WHERE household_id=$1;", h_b)
            == 0
        )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO calendar_events "
                "(household_id, owner_id, title, starts_at, ends_at) "
                "VALUES ($1,$2,'X',$3,$4);",
                h_b,
                owner_b,
                t0,
                t1,
            )
    finally:
        await app.close()


async def test_calendar_feeds_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, member_a, member_b, user = (uuid.uuid4() for _ in range(5))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO calendar_feeds (household_id, member_id, token) "
            "VALUES ($1,$2,'tok-a'), ($3,$4,'tok-b');",
            h_a,
            member_a,
            h_b,
            member_b,
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
        # The app role (household A) sees only A's feed, never B's.
        assert [r["token"] for r in await app.fetch("SELECT token FROM calendar_feeds;")] == [
            "tok-a"
        ]
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO calendar_feeds (household_id, member_id, token) VALUES ($1,$2,'x');",
                h_b,
                member_b,
            )
    finally:
        await app.close()
    # The cross-household maint lookup (maint_all policy) is exercised end-to-end by the feed
    # fetch in test_calendar_http (custode_maint isn't provisioned in this RLS-only fixture).
