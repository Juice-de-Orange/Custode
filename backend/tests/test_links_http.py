"""End-to-end HTTP tests for object_links (Testcontainers PG 18 + Redis): create, list from either
endpoint, direction-independent idempotency, self-link rejection, unlink, household isolation.
Skipped without Docker."""

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


async def _admin_household(client: AsyncClient) -> str:
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Admin"},
    )
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return (await client.get("/v1/auth/me")).json()["user_id"]


async def test_link_create_list_and_idempotent(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        guide, recipe = str(uuid.uuid4()), str(uuid.uuid4())
        created = await admin.post(
            "/v1/links",
            json={
                "a_type": "guide",
                "a_id": guide,
                "b_type": "recipe",
                "b_id": recipe,
            },
            headers=_csrf(admin),
        )
        assert created.status_code == 201, created.text
        link_id = created.json()["id"]
        assert created.json()["relation"] == "related"

        # Visible from the guide endpoint…
        from_guide = (
            await admin.get("/v1/links", params={"object_type": "guide", "object_id": guide})
        ).json()
        assert [link["id"] for link in from_guide] == [link_id]
        # …and from the recipe endpoint (the same single link).
        from_recipe = (
            await admin.get("/v1/links", params={"object_type": "recipe", "object_id": recipe})
        ).json()
        assert [link["id"] for link in from_recipe] == [link_id]

        # Re-linking the same pair in the other direction returns the same link (idempotent).
        again = await admin.post(
            "/v1/links",
            json={"a_type": "recipe", "a_id": recipe, "b_type": "guide", "b_id": guide},
            headers=_csrf(admin),
        )
        assert again.status_code == 201, again.text
        assert again.json()["id"] == link_id
        still_one = (
            await admin.get("/v1/links", params={"object_type": "guide", "object_id": guide})
        ).json()
        assert len(still_one) == 1


async def test_self_link_is_rejected(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        obj = str(uuid.uuid4())
        resp = await admin.post(
            "/v1/links",
            json={"a_type": "guide", "a_id": obj, "b_type": "guide", "b_id": obj},
            headers=_csrf(admin),
        )
        assert resp.status_code == 422


async def test_unlink_removes_the_link(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        link_id = (
            await admin.post(
                "/v1/links",
                json={"a_type": "task", "a_id": a, "b_type": "guide", "b_id": b},
                headers=_csrf(admin),
            )
        ).json()["id"]
        ok = await admin.delete(f"/v1/links/{link_id}", headers=_csrf(admin))
        assert ok.status_code == 204
        gone = await admin.get("/v1/links", params={"object_type": "task", "object_id": a})
        assert gone.json() == []


async def test_links_are_isolated_across_households(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        guide, recipe = str(uuid.uuid4()), str(uuid.uuid4())
        await a.post(
            "/v1/links",
            json={"a_type": "guide", "a_id": guide, "b_type": "recipe", "b_id": recipe},
            headers=_csrf(a),
        )
        # B (other household) sees nothing on the same object_id (RLS).
        on_obj = await b.get("/v1/links", params={"object_type": "guide", "object_id": guide})
        assert on_obj.json() == []
