"""End-to-end HTTP tests for the points ledger (Testcontainers Postgres 18 + Redis). Completing a
task credits the ledger (ADR-0035); balance + movements read back; admin correction grants/claws
back with coverage. Skipped without Docker. Own Postgres fixtures (mirrors test_tasks_http.py)."""

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
    """Register a user + create a household (caller becomes admin). Returns the user_id."""
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    reg = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Chef"},
    )
    assert reg.status_code == 201, reg.text
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    me = await client.get("/v1/auth/me")
    return me.json()["user_id"]


async def _complete_a_task(client: AsyncClient, points: int) -> None:
    tmpl = await client.post(
        "/v1/tasks/templates", json={"title": "Müll", "points": points}, headers=_csrf(client)
    )
    inst = await client.post(
        "/v1/tasks/instances", json={"template_id": tmpl.json()["id"]}, headers=_csrf(client)
    )
    done = await client.post(
        f"/v1/tasks/instances/{inst.json()['id']}/complete",
        headers={**_csrf(client), "If-Match": inst.headers["etag"]},
    )
    assert done.status_code == 200, done.text


async def test_completing_a_task_credits_the_ledger(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 0

        await _complete_a_task(c, points=10)
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 10

        ledger = (await c.get("/v1/economy/ledger")).json()
        assert len(ledger) == 1
        assert ledger[0]["amount"] == 10
        assert ledger[0]["to_account"].startswith("member:")
        assert ledger[0]["ref_type"] == "task_completion"

        # a second completion adds up
        await _complete_a_task(c, points=5)
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 15


async def test_zero_point_task_books_nothing(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        await _complete_a_task(c, points=0)
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 0
        assert (await c.get("/v1/economy/ledger")).json() == []


async def test_admin_correction_grant_and_clawback(app: FastAPI) -> None:
    async with _client(app) as c:
        user_id = await _admin_household(c)
        # grant 20
        grant = await c.post(
            "/v1/economy/corrections",
            json={"member_id": user_id, "amount": 20, "note": "Bonus"},
            headers=_csrf(c),
        )
        assert grant.status_code == 201
        assert grant.json()["balance"] == 20

        # claw back 5 -> 15
        claw = await c.post(
            "/v1/economy/corrections",
            json={"member_id": user_id, "amount": -5},
            headers=_csrf(c),
        )
        assert claw.json()["balance"] == 15

        # claw back below zero is refused (no negative balance)
        too_much = await c.post(
            "/v1/economy/corrections",
            json={"member_id": user_id, "amount": -100},
            headers=_csrf(c),
        )
        assert too_much.status_code == 422
        assert too_much.json()["type"].endswith("insufficient_funds")
        # balance unchanged after the refused claw-back
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 15


async def test_reward_catalog_redeem_and_fulfill(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        # admin creates a reward
        reward = await c.post(
            "/v1/economy/rewards",
            json={"title": "Kinoabend", "cost": 10},
            headers=_csrf(c),
        )
        assert reward.status_code == 201, reward.text
        reward_id = reward.json()["id"]

        # not enough points yet
        broke = await c.post(f"/v1/economy/rewards/{reward_id}/redeem", headers=_csrf(c))
        assert broke.status_code == 422
        assert broke.json()["type"].endswith("insufficient_funds")

        # earn 10, then redeem
        await _complete_a_task(c, points=10)
        redeem = await c.post(f"/v1/economy/rewards/{reward_id}/redeem", headers=_csrf(c))
        assert redeem.status_code == 201, redeem.text
        assert redeem.json()["status"] == "requested"
        # the cost was debited
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 0

        # admin confirm list shows the requested redemption
        pending = (await c.get("/v1/economy/redemptions", params={"status": "requested"})).json()
        assert len(pending) == 1
        redemption_id = pending[0]["id"]

        # fulfill it
        done = await c.post(f"/v1/economy/redemptions/{redemption_id}/fulfill", headers=_csrf(c))
        assert done.status_code == 200
        assert done.json()["status"] == "fulfilled"
        # fulfilling again -> 409
        again = await c.post(f"/v1/economy/redemptions/{redemption_id}/fulfill", headers=_csrf(c))
        assert again.status_code == 409


async def test_reward_stock_runs_out(app: FastAPI) -> None:
    async with _client(app) as c:
        user_id = await _admin_household(c)
        # fund the member with 5 points
        await c.post(
            "/v1/economy/corrections",
            json={"member_id": user_id, "amount": 5},
            headers=_csrf(c),
        )
        reward = await c.post(
            "/v1/economy/rewards",
            json={"title": "Letztes Stück", "cost": 1, "stock": 1},
            headers=_csrf(c),
        )
        reward_id = reward.json()["id"]
        first = await c.post(f"/v1/economy/rewards/{reward_id}/redeem", headers=_csrf(c))
        assert first.status_code == 201
        # stock now 0 -> next redeem refused
        second = await c.post(f"/v1/economy/rewards/{reward_id}/redeem", headers=_csrf(c))
        assert second.status_code == 409
        assert second.json()["type"].endswith("out_of_stock")


async def test_reward_patch_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post(
            "/v1/economy/rewards", json={"title": "Eis", "cost": 3}, headers=_csrf(c)
        )
        reward_id = created.json()["id"]
        etag = created.headers["etag"]
        patched = await c.patch(
            f"/v1/economy/rewards/{reward_id}",
            json={"cost": 4, "active": False},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert patched.status_code == 200
        assert patched.json()["cost"] == 4
        assert patched.json()["active"] is False
        # an inactive reward is hidden from the (member-facing) active listing... but admin sees all
        listed = (await c.get("/v1/economy/rewards")).json()
        assert any(r["id"] == reward_id for r in listed)  # caller is admin -> sees inactive too


async def _join_member(admin: AsyncClient, member: AsyncClient) -> str:
    """Admin invites a member; a fresh user joins -> role member. Returns the member's user_id."""
    invite = await admin.post(
        "/v1/household/invites", json={"role": "member"}, headers=_csrf(admin)
    )
    assert invite.status_code == 201, invite.text
    code = invite.json()["code"]
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await member.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Mit"},
    )
    joined = await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
    assert joined.status_code == 201, joined.text
    return (await member.get("/v1/auth/me")).json()["user_id"]


async def test_thanks_transfers_and_caps(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        admin_id = await _admin_household(admin)
        member_id = await _join_member(admin, member)
        # fund the admin with 50 points
        await admin.post(
            "/v1/economy/corrections",
            json={"member_id": admin_id, "amount": 50},
            headers=_csrf(admin),
        )
        # thank the member 6 -> ok, remaining 4
        first = await admin.post(
            "/v1/economy/thanks",
            json={"to_member_id": member_id, "amount": 6},
            headers=_csrf(admin),
        )
        assert first.status_code == 201, first.text
        assert first.json()["remaining_this_week"] == 4
        # the member received the points
        assert (await member.get("/v1/economy/balance")).json()["balance"] == 6

        # thanking another 6 would exceed the weekly cap of 10 -> 422
        capped = await admin.post(
            "/v1/economy/thanks",
            json={"to_member_id": member_id, "amount": 6},
            headers=_csrf(admin),
        )
        assert capped.status_code == 422
        assert capped.json()["type"].endswith("thanks_cap_reached")

        # thanking yourself is refused
        selfthx = await admin.post(
            "/v1/economy/thanks",
            json={"to_member_id": admin_id, "amount": 1},
            headers=_csrf(admin),
        )
        assert selfthx.status_code == 422


async def test_weekly_challenge_standings(app: FastAPI) -> None:
    async with _client(app) as c:
        user_id = await _admin_household(c)
        await _complete_a_task(c, points=10)
        await _complete_a_task(c, points=5)
        challenge = await c.get("/v1/economy/challenge")
        assert challenge.status_code == 200, challenge.text
        body = challenge.json()
        assert body["thanks_remaining"] == 10
        mine = [s for s in body["standings"] if s["member_id"] == user_id]
        assert mine and mine[0]["points"] == 15


async def test_fairness_account(app: FastAPI) -> None:
    async with _client(app) as c:
        user_id = await _admin_household(c)
        await _complete_a_task(c, points=10)
        fairness = await c.get("/v1/economy/fairness")
        assert fairness.status_code == 200, fairness.text
        body = fairness.json()
        assert body["window_days"] == 30
        mine = [e for e in body["entries"] if e["member_id"] == user_id]
        assert mine and mine[0]["load"] == 10
