"""Sync-Batch property/scenario tests for shopping (ARCHITECTURE §10 matrix) over the real endpoint
(Testcontainers PG 18 + Redis). Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from typing import Any

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


@pytest.fixture(autouse=True)
def pwned_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _zero(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr("app.modules.accounts.service.pwned_count", _zero)


def _client(app_obj: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_obj), base_url="http://test")


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(_CSRF)
    return {"X-CSRF-Token": token} if token else {}


async def _admin_household(client: AsyncClient) -> None:
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    reg = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Koch"},
    )
    assert reg.status_code == 201, reg.text
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text


def _op(entity: str, entity_id: str, op: str, fields: dict[str, Any]) -> dict[str, Any]:
    return {
        "client_op_id": str(uuid.uuid4()),
        "entity": entity,
        "id": entity_id,
        "base_version": 0,
        "op": op,
        "fields": fields,
    }


async def _push(client: AsyncClient, ops: list[dict[str, Any]]) -> dict[str, Any]:
    resp = await client.post("/v1/sync/shopping/batch", json={"ops": ops}, headers=_csrf(client))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _state(body: dict[str, Any], entity_id: str) -> dict[str, Any]:
    return next(s for s in body["applied"] if s["id"] == entity_id)


async def _list_and_item(client: AsyncClient) -> tuple[str, str]:
    list_id, item_id = str(uuid.uuid4()), str(uuid.uuid4())
    await _push(
        client,
        [
            _op("shopping_list", list_id, "upsert", {"name": "Wocheneinkauf"}),
            _op("shopping_item", item_id, "upsert", {"list_id": list_id, "label": "Milch"}),
        ],
    )
    return list_id, item_id


async def test_create_and_readback(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)
        body = await _push(c, [_op("shopping_item", item_id, "upsert", {})])
        item = _state(body, item_id)
        assert item["fields"]["label"] == "Milch"
        assert item["fields"]["checked"] is False
        assert item["deleted"] is False


async def test_field_groups_do_not_clash(app: FastAPI) -> None:
    """Two devices: one checks, one renames — both survive (LWW per field group)."""
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)
        await _push(c, [_op("shopping_item", item_id, "upsert", {"checked": True})])
        body = await _push(c, [_op("shopping_item", item_id, "upsert", {"label": "Vollmilch"})])
        item = _state(body, item_id)
        assert item["fields"]["checked"] is True  # not clobbered by the rename
        assert item["fields"]["label"] == "Vollmilch"


async def test_same_field_last_write_wins(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)
        await _push(c, [_op("shopping_item", item_id, "upsert", {"label": "A"})])
        body = await _push(c, [_op("shopping_item", item_id, "upsert", {"label": "B"})])
        assert _state(body, item_id)["fields"]["label"] == "B"


async def test_idempotent_replay_is_a_noop(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)
        op = _op("shopping_item", item_id, "upsert", {"checked": True})
        first = _state(await _push(c, [op]), item_id)
        replay = _state(await _push(c, [op]), item_id)  # same client_op_id
        assert replay["version"] == first["version"]  # not re-applied, version not bumped
        assert replay["fields"]["checked"] is True


async def test_delete_is_sticky(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)
        await _push(c, [_op("shopping_item", item_id, "delete", {})])
        body = await _push(c, [_op("shopping_item", item_id, "upsert", {"label": "Zombie"})])
        assert _state(body, item_id)["deleted"] is True


async def test_validation_errors(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        missing = await c.post(
            "/v1/sync/shopping/batch",
            json={"ops": [_op("shopping_item", str(uuid.uuid4()), "upsert", {"label": "x"})]},
            headers=_csrf(c),
        )
        assert missing.status_code == 422  # missing required list_id on create
        bad_field = await c.post(
            "/v1/sync/shopping/batch",
            json={"ops": [_op("shopping_list", str(uuid.uuid4()), "upsert", {"bogus": 1})]},
            headers=_csrf(c),
        )
        assert bad_field.status_code == 422  # disallowed field


async def _pull(client: AsyncClient, cursor: str | None = None) -> dict[str, Any]:
    resp = await client.get("/v1/sync/shopping", params={"cursor": cursor} if cursor else {})
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_pull_initial_then_delta(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        list_id, item_id = await _list_and_item(c)
        full = await _pull(c)
        ids = {ch["id"] for ch in full["changes"]}
        assert {list_id, item_id} <= ids
        item = next(ch for ch in full["changes"] if ch["id"] == item_id)
        assert item["op"] == "upsert"
        assert item["fields"]["label"] == "Milch"
        assert full["next_cursor"]  # high-water mark is set

        # A later change shows up in the delta; the unchanged list does not.
        await _push(c, [_op("shopping_item", item_id, "upsert", {"checked": True})])
        delta = await _pull(c, full["next_cursor"])
        delta_ids = [ch["id"] for ch in delta["changes"]]
        assert item_id in delta_ids
        assert list_id not in delta_ids
        assert (
            next(ch for ch in delta["changes"] if ch["id"] == item_id)["fields"]["checked"] is True
        )


async def test_pull_includes_tombstones(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)
        cursor = (await _pull(c))["next_cursor"]
        await _push(c, [_op("shopping_item", item_id, "delete", {})])
        delta = await _pull(c, cursor)
        deleted = next(ch for ch in delta["changes"] if ch["id"] == item_id)
        assert deleted["op"] == "delete"


async def test_pull_invalid_cursor_requires_resync(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        resp = await c.get("/v1/sync/shopping", params={"cursor": "not-a-valid-cursor"})
        assert resp.status_code == 410
        assert resp.json()["type"].endswith("resync_required")


async def test_basic_create_and_pull(app: FastAPI) -> None:
    """Basics are a third sync entity — same batch/pull path as lists/items."""
    async with _client(app) as c:
        await _admin_household(c)
        basic_id = str(uuid.uuid4())
        body = await _push(
            c,
            [_op("shopping_basic", basic_id, "upsert", {"label": "Eier", "category": "Kühlregal"})],
        )
        assert _state(body, basic_id)["fields"]["label"] == "Eier"
        full = await _pull(c)
        assert any(
            ch["entity"] == "shopping_basic" and ch["id"] == basic_id for ch in full["changes"]
        )


async def test_reserve_and_check_stamp_server_owner_unspoofably(app: FastAPI) -> None:
    """``reserve``/``checked`` triggers let the server stamp reserved_by/checked_by; the owner
    columns themselves are not client-writable (T5, ADR-0032 server-authority)."""
    async with _client(app) as c:
        await _admin_household(c)
        _list_id, item_id = await _list_and_item(c)

        reserved = _state(
            await _push(c, [_op("shopping_item", item_id, "upsert", {"reserve": True})]), item_id
        )
        assert reserved["fields"]["reserved_by"] is not None  # server stamped the acting user

        checked = _state(
            await _push(c, [_op("shopping_item", item_id, "upsert", {"checked": True})]), item_id
        )
        assert checked["fields"]["checked_by"] is not None
        assert checked["fields"]["reserved_by"] is not None  # untouched by the check (field groups)

        released = _state(
            await _push(c, [_op("shopping_item", item_id, "upsert", {"reserve": False})]), item_id
        )
        assert released["fields"]["reserved_by"] is None

        # A client cannot set reserved_by directly — it is not a writable field.
        spoof = await c.post(
            "/v1/sync/shopping/batch",
            json={
                "ops": [_op("shopping_item", item_id, "upsert", {"reserved_by": str(uuid.uuid4())})]
            },
            headers=_csrf(c),
        )
        assert spoof.status_code == 422
