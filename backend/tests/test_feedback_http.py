"""End-to-end HTTP tests for feedback (Testcontainers PG 18 + Redis): submit, list own (newest
first), category validation, auth. Skipped without Docker."""

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


async def _admin_household(client: AsyncClient) -> None:
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Admin"},
    )
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text


async def test_submit_and_list_own_feedback(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        first = await admin.post(
            "/v1/feedback",
            json={"category": "bug", "message": "Knopf klemmt", "error_ref": "ABC-123"},
            headers=_csrf(admin),
        )
        assert first.status_code == 201, first.text
        assert first.json()["category"] == "bug"
        assert first.json()["error_ref"] == "ABC-123"
        await admin.post(
            "/v1/feedback",
            json={"category": "idea", "message": "Dunkelmodus"},
            headers=_csrf(admin),
        )
        listed = (await admin.get("/v1/feedback")).json()
        # Newest first; error_ref optional (null when omitted).
        assert [f["message"] for f in listed] == ["Dunkelmodus", "Knopf klemmt"]
        assert listed[0]["error_ref"] is None


async def test_submit_with_optional_diagnostics(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        entry = {
            "at": "2026-06-30T10:00:00Z",
            "route": "/recipes",
            "error_ref": "ABC-1",
            "status": 500,
        }
        ok = await admin.post(
            "/v1/feedback",
            json={
                "category": "bug",
                "message": "Seite hängt",
                "diagnostics": {"app_version": "1.2.3", "entries": [entry]},
            },
            headers=_csrf(admin),
        )
        assert ok.status_code == 201, ok.text


async def test_diagnostics_rejects_extra_keys_and_overlong_buffer(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # extra="forbid": an unknown key cannot smuggle content through the diagnostics object.
        extra = await admin.post(
            "/v1/feedback",
            json={
                "category": "bug",
                "message": "x",
                "diagnostics": {"app_version": "1", "entries": [], "secret": "leak"},
            },
            headers=_csrf(admin),
        )
        assert extra.status_code == 422, extra.text
        # The ring buffer is bounded (max 25 entries).
        overlong = await admin.post(
            "/v1/feedback",
            json={
                "category": "bug",
                "message": "x",
                "diagnostics": {
                    "app_version": "1",
                    "entries": [{"at": "2026-06-30T10:00:00Z"} for _ in range(26)],
                },
            },
            headers=_csrf(admin),
        )
        assert overlong.status_code == 422, overlong.text


async def test_invalid_category_is_422(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        bad = await admin.post(
            "/v1/feedback",
            json={"category": "rant", "message": "nope"},
            headers=_csrf(admin),
        )
        assert bad.status_code == 422


async def test_feedback_requires_auth(app: FastAPI) -> None:
    async with _client(app) as anon:
        resp = await anon.post("/v1/feedback", json={"category": "bug", "message": "x"})
        assert resp.status_code in (401, 403)
