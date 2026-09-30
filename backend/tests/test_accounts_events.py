"""Domain-event emission for accounts (Testcontainers Postgres 18). Proves the
transactional outbox: ``member.joined`` / ``member.role_changed`` / ``member.left`` land
in ``events_outbox`` in the same transaction as the fact change, are household-scoped
(RLS), and a failed (rolled-back) accept emits nothing. Skipped without Docker.

Tests run at the service layer (the emit site) with both engines repointed at the
container; the HTTP-level join path is exercised by ``test_auth_http`` (which now also
emits). Reads use a superuser connection (bypasses RLS) except the scope test, which uses
``custode_app`` to prove isolation."""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

import app.kernel.db.engine as engine_mod
from app.kernel.auth.context import Role
from app.kernel.http.problem import ProblemException
from app.kernel.tenancy.session import scoped_session
from app.modules.accounts import service
from app.settings import get_settings
from conftest import PgDatabase


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    """Repoint both the app (custode_app) and maint (custode_maint) engines (cf.
    test_auth_http) so the service layer talks to the container."""
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = {k: os.environ.get(k) for k in ("CUSTODE_DATABASE_URL", "CUSTODE_DATABASE_URL_MAINT")}
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
    try:
        yield
    finally:
        for eng in (engine_mod._engine, engine_mod._maint_engine):
            if eng is not None:
                await eng.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
        for key, value in prev.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


async def _conn(pg: PgDatabase, user: str, password: str) -> asyncpg.Connection:
    return await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=user,
        password=password,
        database=pg.dbname,
    )


async def _seed_household(
    su: asyncpg.Connection, *, name: str = "H"
) -> tuple[uuid.UUID, uuid.UUID]:
    """Insert a household with one admin (superuser, bypasses RLS). Returns (admin_id, hid)."""
    admin, hid, mid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await su.execute("INSERT INTO users (id, display_name) VALUES ($1, 'Admin')", admin)
    await su.execute("INSERT INTO households (id, name) VALUES ($1, $2)", hid, name)
    await su.execute(
        "INSERT INTO memberships (id, household_id, user_id, role) VALUES ($1, $2, $3, 'admin')",
        mid,
        hid,
        admin,
    )
    return admin, hid


async def _seed_user(su: asyncpg.Connection, name: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await su.execute("INSERT INTO users (id, display_name) VALUES ($1, $2)", uid, name)
    return uid


async def _seed_membership(
    su: asyncpg.Connection, *, hid: uuid.UUID, user_id: uuid.UUID, role: str
) -> uuid.UUID:
    mid = uuid.uuid4()
    await su.execute(
        "INSERT INTO memberships (id, household_id, user_id, role) VALUES ($1, $2, $3, $4)",
        mid,
        hid,
        user_id,
        role,
    )
    return mid


async def _seed_invite(
    su: asyncpg.Connection, *, hid: uuid.UUID, role: str = "member", max_uses: int = 1
) -> str:
    code = uuid.uuid4().hex
    await su.execute(
        "INSERT INTO invites (household_id, code, role, expires_at, max_uses) "
        "VALUES ($1, $2, $3, now() + interval '1 day', $4)",
        hid,
        code,
        role,
        max_uses,
    )
    return code


async def _events(su: asyncpg.Connection, *, household_id: uuid.UUID, etype: str) -> list[dict]:
    rows = await su.fetch(
        "SELECT payload FROM events_outbox WHERE household_id = $1 AND type = $2 "
        "ORDER BY occurred_at",
        household_id,
        etype,
    )
    return [json.loads(r["payload"]) for r in rows]


async def test_accept_invite_emits_member_joined(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        _admin, hid = await _seed_household(su)
        code = await _seed_invite(su, hid=hid)
        joiner = await _seed_user(su, "Joiner")

        out_hid, role = await service.accept_invite(user_id=joiner, code=code)
        assert out_hid == hid
        assert role == Role.member

        events = await _events(su, household_id=hid, etype="member.joined")
        assert len(events) == 1
        assert events[0] == {"user_id": str(joiner), "role": "member"}
    finally:
        await su.close()


async def test_change_role_emits_role_changed(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        admin1, hid = await _seed_household(su)
        admin2 = await _seed_user(su, "Admin2")
        m2 = await _seed_membership(su, hid=hid, user_id=admin2, role="admin")  # 2nd admin

        async with scoped_session(household_id=hid, user_id=admin1) as s:
            await service.change_role(s, membership_id=m2, new_role="member", household_id=hid)

        events = await _events(su, household_id=hid, etype="member.role_changed")
        assert len(events) == 1
        assert events[0] == {"membership_id": str(m2), "user_id": str(admin2), "role": "member"}
        assert await su.fetchval("SELECT role FROM memberships WHERE id = $1", m2) == "member"
    finally:
        await su.close()


async def test_remove_member_emits_left_and_guards_last_admin(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        admin, hid = await _seed_household(su)
        m_admin = await su.fetchval(
            "SELECT id FROM memberships WHERE household_id = $1 AND role = 'admin'", hid
        )
        member = await _seed_user(su, "Member")
        m_member = await _seed_membership(su, hid=hid, user_id=member, role="member")

        async with scoped_session(household_id=hid, user_id=admin) as s:
            await service.remove_member(s, membership_id=m_member, household_id=hid)

        events = await _events(su, household_id=hid, etype="member.left")
        assert len(events) == 1
        assert events[0] == {"membership_id": str(m_member), "user_id": str(member)}
        assert (
            await su.fetchval("SELECT deleted_at FROM memberships WHERE id = $1", m_member)
            is not None
        )

        # Removing the now-sole admin is refused and emits nothing (admin-continuity).
        with pytest.raises(ProblemException) as exc:
            async with scoped_session(household_id=hid, user_id=admin) as s:
                await service.remove_member(s, membership_id=m_admin, household_id=hid)
        assert exc.value.status == 403
        assert len(await _events(su, household_id=hid, etype="member.left")) == 1  # unchanged
    finally:
        await su.close()


async def test_failed_join_emits_no_event(pg: PgDatabase, db: None) -> None:
    """A rolled-back accept (exhausted invite) must leave no event — the outbox row is
    coupled to the membership insert in one transaction."""
    su = await _conn(pg, pg.username, pg.password)
    try:
        _admin, hid = await _seed_household(su)
        code = await _seed_invite(su, hid=hid, max_uses=1)
        u1 = await _seed_user(su, "U1")
        u2 = await _seed_user(su, "U2")

        await service.accept_invite(user_id=u1, code=code)  # consumes the only use
        with pytest.raises(ProblemException):
            await service.accept_invite(user_id=u2, code=code)  # exhausted -> rolls back

        events = await _events(su, household_id=hid, etype="member.joined")
        assert len(events) == 1
        assert events[0]["user_id"] == str(u1)
    finally:
        await su.close()


async def test_events_are_household_scoped(pg: PgDatabase, db: None) -> None:
    """RLS negative: an event emitted under household A is invisible to a custode_app
    session scoped to household B."""
    su = await _conn(pg, pg.username, pg.password)
    try:
        _admin_a, hid_a = await _seed_household(su, name="HA")
        code = await _seed_invite(su, hid=hid_a)
        joiner = await _seed_user(su, "Joiner")
        await service.accept_invite(user_id=joiner, code=code)
        admin_b, hid_b = await _seed_household(su, name="HB")
    finally:
        await su.close()

    app_conn = await _conn(pg, "custode_app", "app")
    try:
        await app_conn.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false)",
            str(hid_b),
            str(admin_b),
        )
        assert await app_conn.fetchval("SELECT count(*) FROM events_outbox") == 0
        await app_conn.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false)",
            str(hid_a),
            str(joiner),
        )
        assert (
            await app_conn.fetchval(
                "SELECT count(*) FROM events_outbox WHERE type = 'member.joined'"
            )
            == 1
        )
    finally:
        await app_conn.close()


async def test_join_count_matches_joined_events(pg: PgDatabase, db: None) -> None:
    """Invariant: one ``member.joined`` per accepted invite — the join-event count tracks
    the (non-deleted) membership count one-for-one."""
    su = await _conn(pg, pg.username, pg.password)
    try:
        _admin, hid = await _seed_household(su)
        n = 4
        for i in range(n):
            code = await _seed_invite(su, hid=hid)
            user = await _seed_user(su, f"U{i}")
            await service.accept_invite(user_id=user, code=code)

        joined = await _events(su, household_id=hid, etype="member.joined")
        assert len(joined) == n
        members = await su.fetchval(
            "SELECT count(*) FROM memberships WHERE household_id = $1 AND deleted_at IS NULL", hid
        )
        assert members - 1 == len(joined)  # minus the seeded admin (created without a join)
    finally:
        await su.close()
