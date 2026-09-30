"""End-to-end HTTP tests for the marketplace escrow lifecycle (Testcontainers PG 18 + Redis):
seller lists an own task (price reserved into escrow) -> buyer accepts (task reassigned) -> buyer
completes -> settle (escrow + base points to buyer). Plus withdraw refunds the seller, and the
guards (broke seller, buying own listing). Skipped without Docker."""

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
    reg = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Verk"},
    )
    assert reg.status_code == 201, reg.text
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return (await client.get("/v1/auth/me")).json()["user_id"]


async def _join_member(admin: AsyncClient, member: AsyncClient) -> str:
    invite = await admin.post(
        "/v1/household/invites", json={"role": "member"}, headers=_csrf(admin)
    )
    code = invite.json()["code"]
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await member.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Kauf"},
    )
    joined = await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
    assert joined.status_code == 201, joined.text
    return (await member.get("/v1/auth/me")).json()["user_id"]


async def _fund(client: AsyncClient, member_id: str, amount: int) -> None:
    resp = await client.post(
        "/v1/economy/corrections",
        json={"member_id": member_id, "amount": amount},
        headers=_csrf(client),
    )
    assert resp.status_code == 201, resp.text


async def _own_instance(client: AsyncClient, owner_id: str, points: int) -> str:
    """Create a template + an instance assigned to ``owner_id``. Returns the instance id."""
    tmpl = await client.post(
        "/v1/tasks/templates", json={"title": "Putzen", "points": points}, headers=_csrf(client)
    )
    inst = await client.post(
        "/v1/tasks/instances",
        json={"template_id": tmpl.json()["id"], "assigned_to": owner_id},
        headers=_csrf(client),
    )
    assert inst.status_code == 201, inst.text
    return inst.json()["id"]


async def _balance(client: AsyncClient) -> int:
    return (await client.get("/v1/economy/balance")).json()["balance"]


async def test_full_escrow_lifecycle(app: FastAPI) -> None:
    async with _client(app) as seller, _client(app) as buyer:
        seller_id = await _admin_household(seller)
        await _join_member(seller, buyer)
        await _fund(seller, seller_id, 20)
        instance_id = await _own_instance(seller, seller_id, points=3)

        # list for 5 -> escrow reserved; seller balance 20 -> 15
        listing = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 5},
            headers=_csrf(seller),
        )
        assert listing.status_code == 201, listing.text
        listing_id = listing.json()["id"]
        assert await _balance(seller) == 15

        # buyer accepts -> task reassigned, listing accepted
        accepted = await buyer.post(
            f"/v1/marketplace/listings/{listing_id}/accept", headers=_csrf(buyer)
        )
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"

        # buyer completes the task -> base points (3); then settle -> escrow (5)
        inst = await buyer.get(f"/v1/tasks/instances/{instance_id}")
        done = await buyer.post(
            f"/v1/tasks/instances/{instance_id}/complete",
            headers={**_csrf(buyer), "If-Match": inst.headers["etag"]},
        )
        assert done.status_code == 200, done.text
        assert await _balance(buyer) == 3  # base points only, escrow still locked

        settled = await seller.post(
            f"/v1/marketplace/listings/{listing_id}/settle", headers=_csrf(seller)
        )
        assert settled.status_code == 200, settled.text
        assert settled.json()["status"] == "settled"
        assert await _balance(buyer) == 8  # base 3 + escrow 5
        assert await _balance(seller) == 15  # unchanged (escrow already left)

        # settling again -> 409 (idempotent guard)
        again = await seller.post(
            f"/v1/marketplace/listings/{listing_id}/settle", headers=_csrf(seller)
        )
        assert again.status_code == 409


async def test_withdraw_refunds_escrow(app: FastAPI) -> None:
    async with _client(app) as seller:
        seller_id = await _admin_household(seller)
        await _fund(seller, seller_id, 10)
        instance_id = await _own_instance(seller, seller_id, points=0)
        listing = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 4},
            headers=_csrf(seller),
        )
        listing_id = listing.json()["id"]
        assert await _balance(seller) == 6  # 10 - 4 in escrow
        withdrawn = await seller.post(
            f"/v1/marketplace/listings/{listing_id}/withdraw", headers=_csrf(seller)
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()["status"] == "withdrawn"
        assert await _balance(seller) == 10  # escrow refunded


async def test_broke_seller_cannot_list(app: FastAPI) -> None:
    async with _client(app) as seller:
        seller_id = await _admin_household(seller)
        instance_id = await _own_instance(seller, seller_id, points=0)  # balance 0
        resp = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 5},
            headers=_csrf(seller),
        )
        assert resp.status_code == 422
        assert resp.json()["type"].endswith("insufficient_funds")


async def test_cannot_buy_own_listing(app: FastAPI) -> None:
    async with _client(app) as seller:
        seller_id = await _admin_household(seller)
        await _fund(seller, seller_id, 10)
        instance_id = await _own_instance(seller, seller_id, points=0)
        listing = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 3},
            headers=_csrf(seller),
        )
        resp = await seller.post(
            f"/v1/marketplace/listings/{listing.json()['id']}/accept", headers=_csrf(seller)
        )
        assert resp.status_code == 422


async def _set_rule(client: AsyncClient, max_price: int) -> None:
    resp = await client.post(
        "/v1/marketplace/auto-accept", json={"max_price": max_price}, headers=_csrf(client)
    )
    assert resp.status_code == 201, resp.text


async def test_auto_accept_fires_on_listing(app: FastAPI) -> None:
    async with _client(app) as seller, _client(app) as buyer:
        seller_id = await _admin_household(seller)
        await _join_member(seller, buyer)
        await _set_rule(buyer, max_price=10)
        # the buyer's rule is listed back to them
        assert len((await buyer.get("/v1/marketplace/auto-accept")).json()) == 1

        await _fund(seller, seller_id, 20)
        instance_id = await _own_instance(seller, seller_id, points=0)
        listing = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 5},
            headers=_csrf(seller),
        )
        assert listing.status_code == 201, listing.text
        # auto-accepted to the buyer immediately
        assert listing.json()["status"] == "accepted"


async def test_auto_accept_respects_max_price(app: FastAPI) -> None:
    async with _client(app) as seller, _client(app) as buyer:
        seller_id = await _admin_household(seller)
        await _join_member(seller, buyer)
        await _set_rule(buyer, max_price=3)  # below the listing price
        await _fund(seller, seller_id, 20)
        instance_id = await _own_instance(seller, seller_id, points=0)
        listing = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 5},
            headers=_csrf(seller),
        )
        assert listing.json()["status"] == "open"  # no rule matched -> stays open


async def test_auto_accept_fairness_tiebreaker(app: FastAPI) -> None:
    """Two buyers both auto-accept; the one who has carried the LEAST (lower fairness load) wins."""
    async with _client(app) as seller, _client(app) as a, _client(app) as b:
        seller_id = await _admin_household(seller)
        a_id = await _join_member(seller, a)
        b_id = await _join_member(seller, b)
        # give buyer A some load: A completes an assigned task worth 5
        loaded_instance = await _own_instance(seller, a_id, points=5)
        la = await a.get(f"/v1/tasks/instances/{loaded_instance}")
        await a.post(
            f"/v1/tasks/instances/{loaded_instance}/complete",
            headers={**_csrf(a), "If-Match": la.headers["etag"]},
        )
        await _set_rule(a, max_price=10)
        await _set_rule(b, max_price=10)

        await _fund(seller, seller_id, 20)
        instance_id = await _own_instance(seller, seller_id, points=0)
        listing = await seller.post(
            "/v1/marketplace/listings",
            json={"task_instance_id": instance_id, "price": 5},
            headers=_csrf(seller),
        )
        body = listing.json()
        assert body["status"] == "accepted"
        assert body["buyer_id"] == b_id  # B has load 0 < A's load 5 -> B wins
