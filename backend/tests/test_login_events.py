"""Login audit log (Testcontainers Postgres 18, ADR-0025). Proves: success and failure both
record a row; an unknown e-mail records a NULL-user row (no enumeration); the country code is
stored (never the IP); RLS is **user-scoped** (user A never sees user B's attempts); and the
table holds no PII columns. Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

import app.kernel.db.engine as engine_mod
from app.kernel.auth.passwords import hash_password
from app.kernel.http.problem import ProblemException
from app.modules.accounts import service
from app.settings import get_settings
from conftest import PgDatabase

_NIL = "00000000-0000-0000-0000-000000000000"
_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    """Repoint the app + maint engines at the container (cf. test_auth_http)."""
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


async def _seed_user(su: asyncpg.Connection, *, email: str) -> uuid.UUID:
    uid = uuid.uuid4()
    await su.execute(
        "INSERT INTO users (id, email, password_hash, display_name) VALUES ($1, $2, $3, 'U')",
        uid,
        email,
        hash_password(_PASSWORD),
    )
    return uid


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.de"


async def test_login_records_success_event(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        email = _email()
        uid = await _seed_user(su, email=email)
        await service.login(email=email, password=_PASSWORD, country_code="AT")
        rows = await su.fetch(
            "SELECT success, country_code FROM auth_login_events WHERE user_id = $1", uid
        )
        assert len(rows) == 1
        assert rows[0]["success"] is True
        assert rows[0]["country_code"] == "AT"
    finally:
        await su.close()


async def test_login_records_failure_event(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        email = _email()
        uid = await _seed_user(su, email=email)
        with pytest.raises(ProblemException):
            await service.login(email=email, password="wrong-password", country_code="DE")
        rows = await su.fetch(
            "SELECT success, country_code FROM auth_login_events WHERE user_id = $1", uid
        )
        assert len(rows) == 1
        assert rows[0]["success"] is False
        assert rows[0]["country_code"] == "DE"
    finally:
        await su.close()


async def test_login_unknown_email_records_null_user(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        before = await su.fetchval("SELECT count(*) FROM auth_login_events WHERE user_id IS NULL")
        with pytest.raises(ProblemException):
            await service.login(email=_email(), password="whatever", country_code=None)
        after = await su.fetchval("SELECT count(*) FROM auth_login_events WHERE user_id IS NULL")
        assert after == before + 1  # the unknown e-mail leaves no user_id (no enumeration)
    finally:
        await su.close()


async def test_login_events_rls_user_scoped(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        email_a, email_b = _email(), _email()
        uid_a = await _seed_user(su, email=email_a)
        uid_b = await _seed_user(su, email=email_b)
        await service.login(email=email_a, password=_PASSWORD, country_code="AT")
        await service.login(email=email_b, password=_PASSWORD, country_code="AT")
    finally:
        await su.close()

    app_conn = await _conn(pg, "custode_app", "app")
    try:
        await app_conn.execute(
            "SELECT set_config('app.household_id', $1, false), "
            "set_config('app.user_id', $2, false)",
            _NIL,
            str(uid_a),
        )
        # Scoped to A: B's attempt is invisible; A sees its own.
        assert (
            await app_conn.fetchval(
                "SELECT count(*) FROM auth_login_events WHERE user_id = $1", uid_b
            )
            == 0
        )
        assert await app_conn.fetchval("SELECT count(*) FROM auth_login_events") == 1
    finally:
        await app_conn.close()


async def test_login_events_table_has_no_pii(pg: PgDatabase, db: None) -> None:
    su = await _conn(pg, pg.username, pg.password)
    try:
        cols = await su.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'auth_login_events'"
        )
        names = {r["column_name"] for r in cols}
        # Exactly these columns — no ip / email / token / user_agent ever (ADR-0025, §12).
        assert names == {"id", "user_id", "success", "country_code", "created_at"}
    finally:
        await su.close()
