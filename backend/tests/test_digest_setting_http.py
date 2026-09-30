"""HTTP tests for the household digest opt-out (Testcontainers PG 18 + Redis, P8-S7b): admin reads +
toggles ``digest_enabled``; a user without an active household (no admin role) is forbidden. Skipped
without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
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


@pytest.fixture
def app(db: None, redis_db: None) -> FastAPI:
    return create_app()


def _client(app_obj: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_obj), base_url="http://test")


@pytest.fixture(autouse=True)
def pwned_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _zero(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr("app.modules.accounts.service.pwned_count", _zero)


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(_CSRF)
    return {"X-CSRF-Token": token} if token else {}


async def _register(client: AsyncClient) -> None:
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "U"},
    )


async def test_admin_reads_and_toggles_digest(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _register(admin)
        await admin.post("/v1/households", json={"name": "Familie"}, headers=_csrf(admin))

        # Default on.
        assert (await admin.get("/v1/household/digest")).json()["enabled"] is True
        # Turn off, then back on — both reflected.
        off = await admin.patch(
            "/v1/household/digest", json={"enabled": False}, headers=_csrf(admin)
        )
        assert off.status_code == 200 and off.json()["enabled"] is False
        assert (await admin.get("/v1/household/digest")).json()["enabled"] is False
        on = await admin.patch("/v1/household/digest", json={"enabled": True}, headers=_csrf(admin))
        assert on.json()["enabled"] is True


async def test_digest_requires_admin_household(app: FastAPI) -> None:
    async with _client(app) as user:
        await _register(user)  # registered but no household -> no admin role
        assert (await user.get("/v1/household/digest")).status_code == 403
    async with _client(app) as anon:
        assert (await anon.get("/v1/household/digest")).status_code in (401, 403)
