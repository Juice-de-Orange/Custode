"""End-to-end HTTP tests for tasks (Testcontainers Postgres 18 + Redis). Templates CRUD + If-Match,
instance creation (from-template snapshot + ad-hoc), the completion state machine + emitted
``task.completed`` event, and the admin/member role guards. Skipped without Docker; the Postgres
and Redis fixtures come from conftest.py."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
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
    reg = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Nutzer"},
    )
    assert reg.status_code == 201, reg.text


async def _admin_household(client: AsyncClient) -> None:
    """Register a user and create a household (caller becomes admin in it)."""
    await _register(client)
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text


async def _join_as_member(admin: AsyncClient, member: AsyncClient) -> None:
    """Admin invites; a fresh user (``member`` client) registers and joins -> role member."""
    invite = await admin.post(
        "/v1/household/invites", json={"role": "member"}, headers=_csrf(admin)
    )
    assert invite.status_code == 201, invite.text
    code = invite.json()["code"]
    await _register(member)
    joined = await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
    assert joined.status_code == 201, joined.text
    assert joined.json()["role"] == "member"


async def test_template_crud_and_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post(
            "/v1/tasks/templates",
            json={"title": "Müll rausbringen", "points": 5, "outdoor": True},
            headers=_csrf(c),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        template_id = body["id"]
        etag = created.headers["etag"]
        assert body["points"] == 5
        assert body["rotation"] == "open"

        # list + get
        assert any(t["id"] == template_id for t in (await c.get("/v1/tasks/templates")).json())
        got = await c.get(f"/v1/tasks/templates/{template_id}")
        assert got.status_code == 200
        assert got.headers["etag"] == etag

        # patch with the current ETag bumps the version
        patched = await c.patch(
            f"/v1/tasks/templates/{template_id}",
            json={"title": "Müll & Altpapier", "points": 8},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert patched.status_code == 200
        assert patched.json()["title"] == "Müll & Altpapier"
        assert patched.json()["points"] == 8
        assert patched.headers["etag"] != etag

        # a stale ETag is refused
        stale = await c.patch(
            f"/v1/tasks/templates/{template_id}",
            json={"title": "X"},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert stale.status_code == 412
        assert stale.json()["type"].endswith("precondition_failed")

        # soft-delete -> gone
        assert (
            await c.delete(f"/v1/tasks/templates/{template_id}", headers=_csrf(c))
        ).status_code == 204
        assert (await c.get(f"/v1/tasks/templates/{template_id}")).status_code == 404


async def test_template_requires_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post("/v1/tasks/templates", json={"title": "Saugen"}, headers=_csrf(c))
        template_id = created.json()["id"]
        resp = await c.patch(
            f"/v1/tasks/templates/{template_id}", json={"title": "Wischen"}, headers=_csrf(c)
        )
        assert resp.status_code == 428
        assert resp.json()["type"].endswith("precondition_required")


async def test_instance_from_template_snapshots(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        tmpl = await c.post(
            "/v1/tasks/templates", json={"title": "Müll", "points": 5}, headers=_csrf(c)
        )
        template_id = tmpl.json()["id"]
        inst = await c.post(
            "/v1/tasks/instances", json={"template_id": template_id}, headers=_csrf(c)
        )
        assert inst.status_code == 201, inst.text
        body = inst.json()
        assert body["title"] == "Müll"
        assert body["points"] == 5
        assert body["status"] == "open"
        assert body["template_id"] == template_id


async def test_instance_ad_hoc(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        inst = await c.post("/v1/tasks/instances", json={"title": "Spülen"}, headers=_csrf(c))
        assert inst.status_code == 201, inst.text
        body = inst.json()
        assert body["points"] == 0
        assert body["template_id"] is None
        # ad-hoc without a title is rejected (no template to snapshot from)
        bad = await c.post("/v1/tasks/instances", json={}, headers=_csrf(c))
        assert bad.status_code == 422


async def test_complete_instance_transitions_and_emits(app: FastAPI, pg: PgDatabase) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        tmpl = await c.post(
            "/v1/tasks/templates", json={"title": "Müll", "points": 7}, headers=_csrf(c)
        )
        inst = await c.post(
            "/v1/tasks/instances", json={"template_id": tmpl.json()["id"]}, headers=_csrf(c)
        )
        instance_id = inst.json()["id"]
        etag = inst.headers["etag"]

        done = await c.post(
            f"/v1/tasks/instances/{instance_id}/complete",
            headers={**_csrf(c), "If-Match": etag},
        )
        assert done.status_code == 200, done.text
        body = done.json()
        assert body["status"] == "done"
        assert body["done_at"] is not None
        assert body["done_by"] is not None

    # the task.completed event landed in the outbox with points + instance_id
    events = await _completed_events(pg, instance_id)
    assert events, "task.completed event was not emitted"
    assert events[0]["points"] == 7
    assert events[0]["instance_id"] == instance_id
    assert events[0]["done_by"] == body["done_by"]


async def test_complete_twice_conflicts(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        inst = await c.post("/v1/tasks/instances", json={"title": "Spülen"}, headers=_csrf(c))
        instance_id = inst.json()["id"]
        first = await c.post(
            f"/v1/tasks/instances/{instance_id}/complete",
            headers={**_csrf(c), "If-Match": inst.headers["etag"]},
        )
        assert first.status_code == 200
        # refresh ETag, then complete again -> not open -> 409
        fresh = await c.get(f"/v1/tasks/instances/{instance_id}")
        second = await c.post(
            f"/v1/tasks/instances/{instance_id}/complete",
            headers={**_csrf(c), "If-Match": fresh.headers["etag"]},
        )
        assert second.status_code == 409
        assert second.json()["type"].endswith("invalid_state")


async def test_complete_requires_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        inst = await c.post("/v1/tasks/instances", json={"title": "Spülen"}, headers=_csrf(c))
        instance_id = inst.json()["id"]
        # missing If-Match -> 428
        miss = await c.post(f"/v1/tasks/instances/{instance_id}/complete", headers=_csrf(c))
        assert miss.status_code == 428
        # stale If-Match -> 412
        stale = await c.post(
            f"/v1/tasks/instances/{instance_id}/complete",
            headers={**_csrf(c), "If-Match": "9999"},
        )
        assert stale.status_code == 412


async def test_list_instances_filters_open(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        a = await c.post("/v1/tasks/instances", json={"title": "Offen"}, headers=_csrf(c))
        b = await c.post("/v1/tasks/instances", json={"title": "Erledigt"}, headers=_csrf(c))
        await c.post(
            f"/v1/tasks/instances/{b.json()['id']}/complete",
            headers={**_csrf(c), "If-Match": b.headers["etag"]},
        )
        # default == open
        open_ids = [i["id"] for i in (await c.get("/v1/tasks/instances")).json()]
        assert a.json()["id"] in open_ids
        assert b.json()["id"] not in open_ids
        # explicit all sees both
        all_ids = [
            i["id"] for i in (await c.get("/v1/tasks/instances", params={"status": "all"})).json()
        ]
        assert {a.json()["id"], b.json()["id"]} <= set(all_ids)


async def test_member_guards(app: FastAPI) -> None:
    """A non-admin member cannot author templates (admin-only) but can create/complete instances."""
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_as_member(admin, member)

        # member cannot create a template
        forbidden = await member.post(
            "/v1/tasks/templates", json={"title": "Verboten"}, headers=_csrf(member)
        )
        assert forbidden.status_code == 403

        # member CAN create an instance and complete it
        inst = await member.post(
            "/v1/tasks/instances", json={"title": "Mitglied-Aufgabe"}, headers=_csrf(member)
        )
        assert inst.status_code == 201, inst.text
        done = await member.post(
            f"/v1/tasks/instances/{inst.json()['id']}/complete",
            headers={**_csrf(member), "If-Match": inst.headers["etag"]},
        )
        assert done.status_code == 200


# --- helper to inspect the transactional outbox ------------------------------


async def _completed_events(pg: PgDatabase, instance_id: str) -> list[dict[str, object]]:
    """Read ``task.completed`` payloads from the outbox for the given instance (superuser conn)."""
    import json

    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        rows = await conn.fetch(
            "SELECT payload FROM events_outbox WHERE type = 'task.completed' "
            "AND payload->>'instance_id' = $1 ORDER BY occurred_at",
            instance_id,
        )
    finally:
        await conn.close()
    return [json.loads(r["payload"]) for r in rows]


async def test_overdue_task_credits_decayed_points(app: FastAPI) -> None:
    """An instance completed past its due date credits the decayed value (KONZEPT §5.9): a
    10-point task 3 days overdue is worth 7, recorded on the instance and booked to the ledger."""
    from datetime import UTC, datetime, timedelta

    async with _client(app) as c:
        await _admin_household(c)
        tmpl = await c.post(
            "/v1/tasks/templates", json={"title": "Bad", "points": 10}, headers=_csrf(c)
        )
        due = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        inst = await c.post(
            "/v1/tasks/instances",
            json={"template_id": tmpl.json()["id"], "due_at": due},
            headers=_csrf(c),
        )
        done = await c.post(
            f"/v1/tasks/instances/{inst.json()['id']}/complete",
            headers={**_csrf(c), "If-Match": inst.headers["etag"]},
        )
        assert done.status_code == 200, done.text
        assert done.json()["awarded_points"] == 7
        # the ledger balance reflects the decayed award, not the base
        assert (await c.get("/v1/economy/balance")).json()["balance"] == 7


async def test_room_crud_and_heatmap(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        # create two rooms
        kitchen = await c.post(
            "/v1/tasks/rooms",
            json={"name": "Küche", "decay_days": 7, "icon": "🍳"},
            headers=_csrf(c),
        )
        assert kitchen.status_code == 201, kitchen.text
        room_id = kitchen.json()["id"]
        bath = await c.post(
            "/v1/tasks/rooms", json={"name": "Bad", "decay_days": 7}, headers=_csrf(c)
        )
        assert bath.status_code == 201

        # a template in the kitchen, completed now -> kitchen turns green; bath never done -> red
        tmpl = await c.post(
            "/v1/tasks/templates",
            json={"title": "Spülen", "points": 5, "room_id": room_id},
            headers=_csrf(c),
        )
        assert tmpl.json()["room_id"] == room_id
        inst = await c.post(
            "/v1/tasks/instances", json={"template_id": tmpl.json()["id"]}, headers=_csrf(c)
        )
        await c.post(
            f"/v1/tasks/instances/{inst.json()['id']}/complete",
            headers={**_csrf(c), "If-Match": inst.headers["etag"]},
        )

        heatmap = await c.get("/v1/tasks/heatmap")
        assert heatmap.status_code == 200, heatmap.text
        by_room = {r["room_id"]: r for r in heatmap.json()}
        assert by_room[room_id]["status"] == "green"
        assert by_room[room_id]["last_done"] is not None
        bath_id = bath.json()["id"]
        assert by_room[bath_id]["status"] == "red"  # never done
        assert by_room[bath_id]["last_done"] is None

        # S-13: an ad-hoc instance tagged directly to the bath room (no template) refreshes it.
        adhoc = await c.post(
            "/v1/tasks/instances",
            json={"title": "Wischen", "room_id": bath_id},
            headers=_csrf(c),
        )
        assert adhoc.status_code == 201, adhoc.text
        assert adhoc.json()["room_id"] == bath_id
        await c.post(
            f"/v1/tasks/instances/{adhoc.json()['id']}/complete",
            headers={**_csrf(c), "If-Match": adhoc.headers["etag"]},
        )
        by_room2 = {r["room_id"]: r for r in (await c.get("/v1/tasks/heatmap")).json()}
        assert by_room2[bath_id]["status"] == "green"  # direct-room completion counts
        assert by_room2[bath_id]["last_done"] is not None


async def test_room_update_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post(
            "/v1/tasks/rooms", json={"name": "Flur", "decay_days": 14}, headers=_csrf(c)
        )
        room_id = created.json()["id"]
        etag = created.headers["etag"]
        patched = await c.patch(
            f"/v1/tasks/rooms/{room_id}",
            json={"decay_days": 30},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert patched.status_code == 200
        assert patched.json()["decay_days"] == 30
        # delete -> drops out of the heatmap
        assert (await c.delete(f"/v1/tasks/rooms/{room_id}", headers=_csrf(c))).status_code == 204
        assert all(r["room_id"] != room_id for r in (await c.get("/v1/tasks/heatmap")).json())
