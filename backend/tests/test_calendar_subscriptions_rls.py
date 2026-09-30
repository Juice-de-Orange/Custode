"""RLS negative test for external_calendar_subscriptions (Testcontainers PG 18, P9-S2).
Household A cannot see B's subscriptions; WITH CHECK refuses a foreign household_id; the
``maint_all`` policy lets ``custode_maint`` enumerate cross-household (the 9-S3 cron's read
path — created with the table, proven here). Skipped without Docker."""

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


async def test_subscription_rls_isolates_households(migrated_pg: PgDatabase) -> None:
    h_a, h_b, user = (uuid.uuid4() for _ in range(3))

    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO external_calendar_subscriptions "
            "(household_id, member_id, label, caldav_url) "
            "VALUES ($1,$3,'A','https://a.example/dav'), ($2,$3,'B','https://b.example/dav');",
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
        rows = await app.fetch("SELECT label FROM external_calendar_subscriptions;")
        assert [r["label"] for r in rows] == ["A"]  # B's subscription is invisible
        assert (
            await app.fetchval(
                "SELECT count(*) FROM external_calendar_subscriptions WHERE household_id=$1;", h_b
            )
            == 0
        )
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await app.execute(
                "INSERT INTO external_calendar_subscriptions "
                "(household_id, member_id, label, caldav_url) "
                "VALUES ($1,$2,'X','https://x.example/dav');",
                h_b,
                user,
            )
    finally:
        await app.close()


async def test_maint_role_enumerates_cross_household(migrated_pg: PgDatabase) -> None:
    # The 9-S3 pull-sync cron lists due subscriptions across households under custode_maint
    # (SELECT-only maint_all policy) — and must NOT be able to write through it.
    h_c, h_d, user = (uuid.uuid4() for _ in range(3))
    su = await _connect(migrated_pg, migrated_pg.username, migrated_pg.password)
    try:
        await su.execute(
            "INSERT INTO external_calendar_subscriptions "
            "(household_id, member_id, label, caldav_url) "
            "VALUES ($1,$3,'C','https://c.example/dav'), ($2,$3,'D','https://d.example/dav');",
            h_c,
            h_d,
            user,
        )
    finally:
        await su.close()

    maint = await _connect(migrated_pg, "custode_maint", "maint")
    try:
        count = await maint.fetchval(
            "SELECT count(*) FROM external_calendar_subscriptions WHERE household_id = ANY($1);",
            [h_c, h_d],
        )
        assert count == 2  # rows from BOTH households are visible without a tenant scope
        with pytest.raises(asyncpg.exceptions.InsufficientPrivilegeError):
            await maint.execute("UPDATE external_calendar_subscriptions SET label = 'hijack';")
    finally:
        await maint.close()
