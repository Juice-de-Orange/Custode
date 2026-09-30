"""End-to-end HTTP tests for the Zuruf capture + inbox triage (Testcontainers PG 18 + Redis):
a free-text Zuruf becomes a proposed capture; confirming a shopping proposal creates a list item
(via the sync path, source=zuruf); confirming a task proposal creates a personal task; confirm is
idempotent; dismiss closes it; foreign captures 404; children are excluded (403). Skipped without
Docker."""

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
    """Register + create a household. Returns the household_id."""
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    reg = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Admin"},
    )
    assert reg.status_code == 201, reg.text
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return created.json()["household_id"]


async def _zuruf(client: AsyncClient, raw_text: str) -> dict[str, object]:
    resp = await client.post("/v1/capture", json={"raw_text": raw_text}, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_zuruf_creates_proposed_capture_in_inbox(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "Milch kaufen")
        assert body["status"] == "proposed"
        assert body["proposal"]["target"] == "shopping"
        assert body["proposal"]["label"] == "Milch"

        inbox = await admin.get("/v1/capture/inbox")
        assert inbox.status_code == 200
        assert [c["id"] for c in inbox.json()] == [body["id"]]


async def test_confirm_shopping_creates_list_item_via_sync(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "2 Liter Milch besorgen")
        confirm = await admin.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(admin))
        assert confirm.status_code == 200, confirm.text
        assert confirm.json()["status"] == "confirmed"

        pull = await admin.get("/v1/sync/shopping")
        assert pull.status_code == 200, pull.text
        items = [c for c in pull.json()["changes"] if c["entity"] == "shopping_item"]
        assert len(items) == 1
        fields = items[0]["fields"]
        assert fields["label"] == "Milch"
        assert fields["qty"] == "2"
        assert fields["source"] == "zuruf"

        # The capture left the inbox.
        assert (await admin.get("/v1/capture/inbox")).json() == []


async def test_confirm_is_idempotent(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "Brot holen")
        first = await admin.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(admin))
        assert first.status_code == 200
        # Re-confirming an already-confirmed capture is rejected (409) — no duplicate item.
        again = await admin.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(admin))
        assert again.status_code == 409

        pull = await admin.get("/v1/sync/shopping")
        items = [c for c in pull.json()["changes"] if c["entity"] == "shopping_item"]
        assert len(items) == 1


async def test_confirm_task_creates_personal_task(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "#task Müll rausbringen")
        assert body["proposal"]["target"] == "task"
        confirm = await admin.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(admin))
        assert confirm.status_code == 200, confirm.text

        instances = await admin.get("/v1/tasks/instances")
        titles = [i["title"] for i in instances.json()]
        assert "Müll rausbringen" in titles


async def test_confirm_unsortiert_has_no_target(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "Kevin anrufen")
        assert body["proposal"]["target"] == "none"
        confirm = await admin.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(admin))
        assert confirm.status_code == 409


async def test_dismiss_closes_capture(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "Kevin anrufen")
        dismissed = await admin.post(f"/v1/capture/{body['id']}/dismiss", headers=_csrf(admin))
        assert dismissed.status_code == 200
        assert dismissed.json()["status"] == "dismissed"
        assert (await admin.get("/v1/capture/inbox")).json() == []


async def test_foreign_capture_is_not_found(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as other:
        await _admin_household(admin)
        body = await _zuruf(admin, "Milch kaufen")
        await _admin_household(other)  # a separate household
        resp = await other.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(other))
        assert resp.status_code == 404


async def _drain_outbox_for_capture() -> None:
    """Run the outbox dispatcher once with the capture handler bound (mirrors the worker composition
    root, ADR-0039) so a ``shopping.item.checked`` event activates armed follow-up tasks."""
    from app.kernel.db.engine import get_maint_sessionmaker
    from app.kernel.events.dispatcher import OutboxDispatcher
    from app.modules.capture.handlers import register_capture_handlers

    dispatcher = OutboxDispatcher()
    register_capture_handlers(dispatcher)
    factory = get_maint_sessionmaker()
    async with factory() as session:
        await dispatcher.dispatch_once(session)


async def test_deo_action_chain_end_to_end(app: FastAPI) -> None:
    """Deo-Fall E2E ohne LLM (KONZEPT §5.17, Done-Kriterium Teil 3): Zuruf mit Folge-Klausel ->
    Posten + vorgemerkte (armed) Aufgabe; Abhaken des Postens schaltet die Aufgabe scharf (open)."""
    async with _client(app) as admin:
        await _admin_household(admin)
        body = await _zuruf(admin, "Deo kaufen, dann in den Rucksack")
        assert body["proposal"]["target"] == "shopping"
        assert body["proposal"]["label"] == "Deo"
        assert body["proposal"]["follow_up"]["label"] == "in den Rucksack"

        confirm = await admin.post(f"/v1/capture/{body['id']}/confirm", headers=_csrf(admin))
        assert confirm.status_code == 200, confirm.text

        # The follow-up task exists but is armed (not in the default open list yet).
        armed = await admin.get("/v1/tasks/instances?status=armed")
        assert [t["title"] for t in armed.json()] == ["in den Rucksack"]
        open_before = await admin.get("/v1/tasks/instances?status=open")
        assert "in den Rucksack" not in [t["title"] for t in open_before.json()]

        # Find the Zuruf-created shopping item and check it off (emits shopping.item.checked).
        pull = await admin.get("/v1/sync/shopping")
        items = [c for c in pull.json()["changes"] if c["entity"] == "shopping_item"]
        item_id = items[0]["id"]
        check = await admin.post(
            "/v1/sync/shopping/batch",
            json={
                "ops": [
                    {
                        "client_op_id": str(uuid.uuid4()),
                        "entity": "shopping_item",
                        "id": item_id,
                        "base_version": 0,
                        "op": "upsert",
                        "fields": {"checked": True},
                    }
                ]
            },
            headers=_csrf(admin),
        )
        assert check.status_code == 200, check.text

        # The worker (here: driven inline) delivers the event -> the armed task is activated.
        await _drain_outbox_for_capture()
        open_after = await admin.get("/v1/tasks/instances?status=open")
        assert "in den Rucksack" in [t["title"] for t in open_after.json()]
        assert (await admin.get("/v1/tasks/instances?status=armed")).json() == []


async def test_child_cannot_capture(app: FastAPI) -> None:
    async with _client(app) as admin:
        household_id = await _admin_household(admin)
        child_create = await admin.post(
            "/v1/household/children",
            json={"display_name": "Kind", "username": "kind1", "pin": "1234"},
            headers=_csrf(admin),
        )
        assert child_create.status_code == 201, child_create.text
        async with _client(app) as child:
            login = await child.post(
                "/v1/auth/child-login",
                json={"household_id": household_id, "username": "kind1", "pin": "1234"},
            )
            assert login.status_code == 200, login.text
            resp = await child.post(
                "/v1/capture", json={"raw_text": "Milch kaufen"}, headers=_csrf(child)
            )
            assert resp.status_code == 403
