"""Login DB tests (Testcontainers Postgres 18): authenticate + start a refresh
session via the maint role. Repoints the global *maint* engine at the container
(the login bootstrap runs cross-user as custode_maint). Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest

import app.kernel.db.engine as engine_mod
from app.kernel.auth.passwords import hash_password
from app.kernel.auth.tokens import hash_token
from app.kernel.http.problem import ProblemException
from app.modules.accounts.service import login, logout, refresh
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret


@pytest.fixture
async def maint_db(pg: PgDatabase) -> AsyncIterator[None]:
    """Repoint the global maint engine at the container as custode_maint."""
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    prev = os.environ.get("CUSTODE_DATABASE_URL_MAINT")
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._maint_engine = None
    engine_mod._maint_sessionmaker = None
    try:
        yield
    finally:
        if engine_mod._maint_engine is not None:
            await engine_mod._maint_engine.dispose()
        engine_mod._maint_engine = None
        engine_mod._maint_sessionmaker = None
        if prev is None:
            os.environ.pop("CUSTODE_DATABASE_URL_MAINT", None)
        else:
            os.environ["CUSTODE_DATABASE_URL_MAINT"] = prev
        get_settings.cache_clear()


async def _seed_user(pg: PgDatabase, *, email: str, password: str) -> uuid.UUID:
    uid = uuid.uuid4()
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await conn.execute(
            "INSERT INTO users (id, email, password_hash, display_name) VALUES ($1, $2, $3, 'U');",
            uid,
            email,
            hash_password(password),
        )
    finally:
        await conn.close()
    return uid


async def _session_row(pg: PgDatabase, session_id: uuid.UUID):
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        return await conn.fetchrow(
            "SELECT user_id, refresh_hash, revoked_at, rotated_at, family_id "
            "FROM auth_sessions WHERE id = $1;",
            session_id,
        )
    finally:
        await conn.close()


async def test_login_success_creates_session(maint_db: None, pg: PgDatabase) -> None:
    uid = await _seed_user(pg, email="user@example.de", password=_PASSWORD)
    result = await login(email="User@Example.DE", password=_PASSWORD, device_label="Firefox")
    assert result.user_id == uid
    assert result.refresh_token
    row = await _session_row(pg, result.session_id)
    assert row is not None
    assert row["user_id"] == uid
    # Stored hashed, never clear-text.
    assert row["refresh_hash"] == hash_token(result.refresh_token)
    assert row["revoked_at"] is None


async def test_login_wrong_password(maint_db: None, pg: PgDatabase) -> None:
    await _seed_user(pg, email="wrongpw@example.de", password=_PASSWORD)
    with pytest.raises(ProblemException) as ei:
        await login(email="wrongpw@example.de", password="falsches-passwort-123")
    assert ei.value.status == 401
    assert ei.value.slug == "invalid_credentials"


async def test_login_unknown_email(maint_db: None) -> None:
    with pytest.raises(ProblemException) as ei:
        await login(email="niemand@example.de", password="irgendein-passwort-123")
    assert ei.value.status == 401


async def test_refresh_rotates_token(maint_db: None, pg: PgDatabase) -> None:
    await _seed_user(pg, email="rotate@example.de", password=_PASSWORD)
    first = await login(email="rotate@example.de", password=_PASSWORD)
    second = await refresh(refresh_token=first.refresh_token)
    assert second.refresh_token != first.refresh_token
    assert second.user_id == first.user_id
    old = await _session_row(pg, first.session_id)
    new = await _session_row(pg, second.session_id)
    assert old is not None and new is not None
    assert old["rotated_at"] is not None  # consumed
    assert new["rotated_at"] is None  # active
    assert old["family_id"] == new["family_id"]  # same rotation family


async def test_refresh_reuse_revokes_family(maint_db: None, pg: PgDatabase) -> None:
    await _seed_user(pg, email="reuse@example.de", password=_PASSWORD)
    first = await login(email="reuse@example.de", password=_PASSWORD)
    second = await refresh(refresh_token=first.refresh_token)  # rotate once
    # Re-presenting the consumed token is a theft signal.
    with pytest.raises(ProblemException) as ei:
        await refresh(refresh_token=first.refresh_token)
    assert ei.value.slug == "token_reuse"
    # The whole family is burned, including the otherwise-valid 'second'.
    row = await _session_row(pg, second.session_id)
    assert row is not None and row["revoked_at"] is not None


async def test_refresh_invalid_token(maint_db: None) -> None:
    with pytest.raises(ProblemException) as ei:
        await refresh(refresh_token="kein-gueltiger-refresh-token")
    assert ei.value.slug == "invalid_token"


async def test_logout_revokes_and_blocks_refresh(
    maint_db: None, pg: PgDatabase, redis_db: None
) -> None:
    """Braucht seit 11-B3 Redis: ``logout`` beendet Sitzung **und** Tokens in einem Zug, statt die
    zweite Hälfte davon abhängig zu machen, welches Cookie beim Server ankam."""
    await _seed_user(pg, email="logout@example.de", password=_PASSWORD)
    first = await login(email="logout@example.de", password=_PASSWORD)
    await logout(refresh_token=first.refresh_token)
    row = await _session_row(pg, first.session_id)
    assert row is not None and row["revoked_at"] is not None
    # A revoked token cannot refresh (reuse-detection path).
    with pytest.raises(ProblemException):
        await refresh(refresh_token=first.refresh_token)
