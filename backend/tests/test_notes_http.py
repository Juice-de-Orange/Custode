"""End-to-end HTTP tests for notes (Testcontainers PG 18 + Redis): CRUD, pin, If-Match concurrency,
list ordering. Skipped without Docker."""

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


async def test_create_get_and_list_note(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        created = await admin.post(
            "/v1/notes",
            json={"title": "Einkauf", "body_md": "# Milch\n- 2 Liter"},
            headers=_csrf(admin),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["title"] == "Einkauf"
        assert body["pinned"] is False
        assert body["author_id"] == user_id
        note_id = body["id"]

        fetched = await admin.get(f"/v1/notes/{note_id}")
        assert fetched.status_code == 200
        assert fetched.json()["body_md"] == "# Milch\n- 2 Liter"
        assert fetched.headers["ETag"] == '"1"'

        listed = (await admin.get("/v1/notes")).json()
        assert [n["id"] for n in listed] == [note_id]


async def test_pinned_notes_sort_first(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await admin.post("/v1/notes", json={"title": "lose"}, headers=_csrf(admin))
        pinned = await admin.post(
            "/v1/notes", json={"title": "wichtig", "pinned": True}, headers=_csrf(admin)
        )
        pinned_id = pinned.json()["id"]
        listed = (await admin.get("/v1/notes")).json()
        assert listed[0]["id"] == pinned_id  # pinned sorts first
        only_pinned = (await admin.get("/v1/notes", params={"pinned": True})).json()
        assert [n["id"] for n in only_pinned] == [pinned_id]


async def test_patch_with_if_match_and_stale_412(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        note_id = (
            await admin.post("/v1/notes", json={"title": "Entwurf"}, headers=_csrf(admin))
        ).json()["id"]
        # Correct If-Match bumps the version.
        ok = await admin.patch(
            f"/v1/notes/{note_id}",
            json={"title": "Final", "pinned": True},
            headers={**_csrf(admin), "If-Match": '"1"'},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["title"] == "Final"
        assert ok.json()["pinned"] is True
        assert ok.headers["ETag"] == '"2"'
        # Stale If-Match -> 412.
        stale = await admin.patch(
            f"/v1/notes/{note_id}",
            json={"title": "Nope"},
            headers={**_csrf(admin), "If-Match": '"1"'},
        )
        assert stale.status_code == 412


async def test_delete_note_then_404(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        note_id = (
            await admin.post("/v1/notes", json={"title": "weg"}, headers=_csrf(admin))
        ).json()["id"]
        deleted = await admin.delete(f"/v1/notes/{note_id}", headers=_csrf(admin))
        assert deleted.status_code == 204
        assert (await admin.get(f"/v1/notes/{note_id}")).status_code == 404
        assert (await admin.get("/v1/notes")).json() == []


async def test_trash_then_untrash_roundtrip(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        note_id = (
            await admin.post("/v1/notes", json={"title": "ups"}, headers=_csrf(admin))
        ).json()["id"]
        await admin.delete(f"/v1/notes/{note_id}", headers=_csrf(admin))

        # Trashed: out of the active list, present in the trash with a deleted_at stamp.
        assert (await admin.get("/v1/notes")).json() == []
        trash = (await admin.get("/v1/notes/trash")).json()
        assert [n["id"] for n in trash] == [note_id]
        assert trash[0]["title"] == "ups"
        assert trash[0]["deleted_at"] is not None

        # Restore: back in the active list, gone from the trash, fetchable again.
        restored = await admin.post(f"/v1/notes/{note_id}/untrash", headers=_csrf(admin))
        assert restored.status_code == 200, restored.text
        assert restored.json()["id"] == note_id
        assert [n["id"] for n in (await admin.get("/v1/notes")).json()] == [note_id]
        assert (await admin.get("/v1/notes/trash")).json() == []
        assert (await admin.get(f"/v1/notes/{note_id}")).status_code == 200

        # Untrashing something not in the trash -> 404.
        assert (
            await admin.post(f"/v1/notes/{note_id}/untrash", headers=_csrf(admin))
        ).status_code == 404
        assert (
            await admin.post(f"/v1/notes/{uuid.uuid4()}/untrash", headers=_csrf(admin))
        ).status_code == 404


async def _edit(client: AsyncClient, note_id: str, title: str, etag: str) -> str:
    resp = await client.patch(
        f"/v1/notes/{note_id}",
        json={"title": title},
        headers={**_csrf(client), "If-Match": etag},
    )
    assert resp.status_code == 200, resp.text
    return resp.headers["ETag"]


async def test_versions_are_archived_and_capped_at_five(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await admin.post("/v1/notes", json={"title": "v1"}, headers=_csrf(admin))
        note_id = created.json()["id"]
        etag = created.headers["ETag"]
        # Seven content edits -> 7 prior versions exist, but only the latest 5 are kept.
        for n in range(2, 9):
            etag = await _edit(admin, note_id, f"v{n}", etag)
        versions = (await admin.get(f"/v1/notes/{note_id}/versions")).json()
        # Newest first, only the latest 5 kept (v2 + v1 pruned).
        assert [v["title"] for v in versions] == ["v7", "v6", "v5", "v4", "v3"]
        assert all(v["version_no"] == int(v["title"][1:]) for v in versions)


async def test_pin_toggle_does_not_create_a_version(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await admin.post("/v1/notes", json={"title": "stabil"}, headers=_csrf(admin))
        note_id = created.json()["id"]
        await admin.patch(
            f"/v1/notes/{note_id}",
            json={"pinned": True},
            headers={**_csrf(admin), "If-Match": created.headers["ETag"]},
        )
        assert (await admin.get(f"/v1/notes/{note_id}/versions")).json() == []


async def test_restore_version_round_trips(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await admin.post(
            "/v1/notes", json={"title": "Original", "body_md": "alt"}, headers=_csrf(admin)
        )
        note_id = created.json()["id"]
        # Edit to v2 (archives "Original" as version_no 1).
        await _edit(admin, note_id, "Geändert", created.headers["ETag"])
        # Restore version 1.
        restored = await admin.post(
            f"/v1/notes/{note_id}/restore",
            params={"version_no": 1},
            headers=_csrf(admin),
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["title"] == "Original"
        assert restored.json()["body_md"] == "alt"
        # The restore itself archived the "Geändert" state -> it is now in the history.
        titles = [v["title"] for v in (await admin.get(f"/v1/notes/{note_id}/versions")).json()]
        assert "Geändert" in titles


async def test_restore_unknown_version_is_404(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        note_id = (await admin.post("/v1/notes", json={"title": "x"}, headers=_csrf(admin))).json()[
            "id"
        ]
        resp = await admin.post(
            f"/v1/notes/{note_id}/restore", params={"version_no": 99}, headers=_csrf(admin)
        )
        assert resp.status_code == 404


async def test_convert_note_to_task(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        note_id = (
            await admin.post("/v1/notes", json={"title": "Fenster putzen"}, headers=_csrf(admin))
        ).json()["id"]
        resp = await admin.post(f"/v1/notes/{note_id}/to-task", headers=_csrf(admin))
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Fenster putzen"
        # The task really exists in the tasks module (points 0, assigned to the caller).
        tasks = (await admin.get("/v1/tasks/instances")).json()
        task = next(t for t in tasks if t["title"] == "Fenster putzen")
        assert task["points"] == 0
        assert task["assigned_to"] == user_id
        # The note itself is non-destructive: it stays.
        assert (await admin.get(f"/v1/notes/{note_id}")).status_code == 200


async def test_convert_missing_note_is_404(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(f"/v1/notes/{uuid.uuid4()}/to-task", headers=_csrf(admin))
        assert resp.status_code == 404


async def test_foreign_note_is_404(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        a_note = (await a.post("/v1/notes", json={"title": "geheim"}, headers=_csrf(a))).json()[
            "id"
        ]
        # B (other household) cannot see A's note.
        assert (await b.get(f"/v1/notes/{a_note}")).status_code == 404
