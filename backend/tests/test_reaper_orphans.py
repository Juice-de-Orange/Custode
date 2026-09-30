"""End-to-end tests for the orphan reaper (P7-S20, Testcontainers PG 18 + Redis): when a commented /
linked object is deleted, its ``comments`` and ``object_links`` are soft-deleted by the outbox
handlers bound at the worker composition root. Keyed only on ``(object_type, object_id)`` — the
generic modules never read the foreign module. Skipped without Docker."""

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


async def _drain_outbox() -> None:
    """Run the outbox dispatcher once with the reaper handlers bound — mirrors the worker
    composition root (P7-S20): a ``*.deleted`` event soft-deletes the dependent comments/links."""
    from app.kernel.db.engine import get_maint_sessionmaker
    from app.kernel.events.dispatcher import OutboxDispatcher
    from app.modules.comments.handlers import register_comments_handlers
    from app.modules.links.handlers import register_links_handlers

    dispatcher = OutboxDispatcher()
    register_comments_handlers(dispatcher)
    register_links_handlers(dispatcher)
    factory = get_maint_sessionmaker()
    async with factory() as session:
        await dispatcher.dispatch_once(session)


async def test_deleting_a_guide_reaps_its_comments_and_links(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        guide_id = (
            await admin.post("/v1/guides", json={"title": "Waschmaschine"}, headers=_csrf(admin))
        ).json()["id"]
        recipe_id = (
            await admin.post(
                "/v1/recipes",
                json={"title": "Pasta", "servings": 2, "ingredients": [], "steps_md": ""},
                headers=_csrf(admin),
            )
        ).json()["id"]

        # A comment on the guide + a link guide<->recipe.
        await admin.post(
            "/v1/comments",
            json={"object_type": "guide", "object_id": guide_id, "body_md": "Achtung"},
            headers=_csrf(admin),
        )
        await admin.post(
            "/v1/links",
            json={"a_type": "guide", "a_id": guide_id, "b_type": "recipe", "b_id": recipe_id},
            headers=_csrf(admin),
        )

        # Delete the guide. Its comment/link are now orphaned until the reaper runs.
        assert (await admin.delete(f"/v1/guides/{guide_id}", headers=_csrf(admin))).status_code in (
            200,
            204,
        )
        thread_before = await admin.get(
            "/v1/comments", params={"object_type": "guide", "object_id": guide_id}
        )
        assert len(thread_before.json()) == 1  # orphan still present pre-reap
        links_before = await admin.get(
            "/v1/links", params={"object_type": "recipe", "object_id": recipe_id}
        )
        assert len(links_before.json()) == 1

        await _drain_outbox()

        # The reaper has soft-deleted both: the guide's thread and the recipe's link are now empty.
        thread_after = await admin.get(
            "/v1/comments", params={"object_type": "guide", "object_id": guide_id}
        )
        assert thread_after.json() == []
        links_after = await admin.get(
            "/v1/links", params={"object_type": "recipe", "object_id": recipe_id}
        )
        assert links_after.json() == []


async def test_reaper_leaves_unrelated_comments_and_links_intact(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        doomed = (
            await admin.post("/v1/guides", json={"title": "Alt"}, headers=_csrf(admin))
        ).json()["id"]
        keep = (
            await admin.post("/v1/guides", json={"title": "Bleibt"}, headers=_csrf(admin))
        ).json()["id"]
        await admin.post(
            "/v1/comments",
            json={"object_type": "guide", "object_id": keep, "body_md": "wichtig"},
            headers=_csrf(admin),
        )

        await admin.delete(f"/v1/guides/{doomed}", headers=_csrf(admin))
        await _drain_outbox()

        # A different guide's comment is untouched (reaper keys on the deleted object only).
        kept = await admin.get("/v1/comments", params={"object_type": "guide", "object_id": keep})
        assert [c["body_md"] for c in kept.json()] == ["wichtig"]
