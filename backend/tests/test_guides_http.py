"""End-to-end HTTP tests for guides (Testcontainers PG 18 + Redis): CRUD, German FTS, category
filter, If-Match concurrency, household isolation. Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

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


async def _create(client: AsyncClient, **body: object) -> dict[str, object]:
    resp = await client.post("/v1/guides", json=body, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_get_and_list_guide(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        created = await _create(
            admin, title="Waschmaschine", body_md="So entkalkst du sie.", category="Haushalt"
        )
        assert created["author_id"] == user_id
        guide_id = created["id"]
        fetched = await admin.get(f"/v1/guides/{guide_id}")
        assert fetched.status_code == 200
        assert fetched.headers["ETag"] == '"1"'
        listed = (await admin.get("/v1/guides")).json()
        assert [g["id"] for g in listed] == [guide_id]


async def test_contact_set_and_cleared(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        # Create with the admin as the contact person.
        created = await _create(admin, title="Heizung", contact_id=user_id)
        assert created["contact_id"] == user_id
        guide_id = created["id"]
        etag = (await admin.get(f"/v1/guides/{guide_id}")).headers["ETag"].strip('"')
        # The contact also surfaces in the light list summary.
        listed = (await admin.get("/v1/guides")).json()
        assert listed[0]["contact_id"] == user_id
        # Explicit null clears it (presence via model_fields_set, not a None check).
        patched = await admin.patch(
            f"/v1/guides/{guide_id}",
            json={"contact_id": None},
            headers={**_csrf(admin), "If-Match": f'"{etag}"'},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["contact_id"] is None


async def test_german_fts_search_stems(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await _create(admin, title="Fahrräder reparieren", body_md="Kette ölen und Bremsen prüfen.")
        await _create(admin, title="Kuchen backen", body_md="Ofen vorheizen.")
        # German stemming: query "Fahrrad" matches the plural "Fahrräder" in the title.
        hits = (await admin.get("/v1/guides", params={"q": "Fahrrad"})).json()
        assert [g["title"] for g in hits] == ["Fahrräder reparieren"]
        # A body term also matches (FTS covers title + body).
        body_hits = (await admin.get("/v1/guides", params={"q": "Bremse"})).json()
        assert [g["title"] for g in body_hits] == ["Fahrräder reparieren"]
        # No match -> empty.
        assert (await admin.get("/v1/guides", params={"q": "Segelboot"})).json() == []


async def test_category_filter(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await _create(admin, title="A", category="Garten")
        await _create(admin, title="B", category="Küche")
        only = (await admin.get("/v1/guides", params={"category": "Garten"})).json()
        assert [g["title"] for g in only] == ["A"]


async def test_patch_with_if_match_and_stale_412(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        guide_id = (await _create(admin, title="Entwurf"))["id"]
        ok = await admin.patch(
            f"/v1/guides/{guide_id}",
            json={"title": "Final", "tags": ["wichtig"]},
            headers={**_csrf(admin), "If-Match": '"1"'},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["title"] == "Final"
        assert ok.json()["tags"] == ["wichtig"]
        assert ok.headers["ETag"] == '"2"'
        stale = await admin.patch(
            f"/v1/guides/{guide_id}",
            json={"title": "Nope"},
            headers={**_csrf(admin), "If-Match": '"1"'},
        )
        assert stale.status_code == 412


async def test_delete_then_404_and_foreign_404(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        guide_id = (await _create(a, title="weg"))["id"]
        assert (await b.get(f"/v1/guides/{guide_id}")).status_code == 404  # other household
        assert (await a.delete(f"/v1/guides/{guide_id}", headers=_csrf(a))).status_code == 204
        assert (await a.get(f"/v1/guides/{guide_id}")).status_code == 404
        assert (await a.get("/v1/guides")).json() == []


def _attach(client: AsyncClient, guide_id: str, name: str, data: bytes) -> object:
    return client.post(
        f"/v1/guides/{guide_id}/attachments",
        files={"file": (name, data, "application/pdf")},
        headers=_csrf(client),
    )


async def test_attachment_upload_list_download_delete(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.kernel.storage import FilesystemStorage

    storage = FilesystemStorage(tmp_path)
    monkeypatch.setattr("app.modules.guides.router.get_storage", lambda: storage)
    monkeypatch.setattr("app.modules.guides.service.get_storage", lambda: storage)
    async with _client(app) as admin:
        await _admin_household(admin)
        guide_id = (await _create(admin, title="Waschmaschine"))["id"]

        up = await _attach(admin, guide_id, "handbuch.pdf", b"%PDF-1.7 body")
        assert up.status_code == 201, up.text
        att = up.json()
        assert att["filename"] == "handbuch.pdf"
        assert att["byte_size"] == len(b"%PDF-1.7 body")

        listed = (await admin.get(f"/v1/guides/{guide_id}/attachments")).json()
        assert [a["id"] for a in listed] == [att["id"]]

        got = await admin.get(f"/v1/guides/{guide_id}/attachments/{att['id']}")
        assert got.status_code == 200
        assert got.content == b"%PDF-1.7 body"
        assert got.headers["content-type"].startswith("application/pdf")

        deleted = await admin.delete(
            f"/v1/guides/{guide_id}/attachments/{att['id']}", headers=_csrf(admin)
        )
        assert deleted.status_code == 204
        assert (await admin.get(f"/v1/guides/{guide_id}/attachments")).json() == []
        # The blob is gone too -> the download 404s.
        assert (
            await admin.get(f"/v1/guides/{guide_id}/attachments/{att['id']}")
        ).status_code == 404


async def test_deleting_a_guide_cascades_its_attachments(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.kernel.storage import FilesystemStorage

    storage = FilesystemStorage(tmp_path)
    monkeypatch.setattr("app.modules.guides.router.get_storage", lambda: storage)
    monkeypatch.setattr("app.modules.guides.service.get_storage", lambda: storage)
    async with _client(app) as admin:
        await _admin_household(admin)
        guide_id = (await _create(admin, title="weg"))["id"]
        att = (await _attach(admin, guide_id, "x.pdf", b"data")).json()

        gone = await admin.delete(f"/v1/guides/{guide_id}", headers=_csrf(admin))
        assert gone.status_code == 204
        # The attachment row is gone (404) and its blob removed.
        assert (
            await admin.get(f"/v1/guides/{guide_id}/attachments/{att['id']}")
        ).status_code == 404
        assert storage.get(f"guide-attachment-{att['id']}") is None


async def test_attachment_upload_503_without_storage(app: FastAPI) -> None:
    # The default test env configures no storage -> NullStorage -> uploads disabled (graceful).
    async with _client(app) as admin:
        await _admin_household(admin)
        guide_id = (await _create(admin, title="X"))["id"]
        up = await _attach(admin, guide_id, "x.pdf", b"data")
        assert up.status_code == 503


async def test_foreign_household_cannot_download_attachment(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.kernel.storage import FilesystemStorage

    storage = FilesystemStorage(tmp_path)
    monkeypatch.setattr("app.modules.guides.router.get_storage", lambda: storage)
    monkeypatch.setattr("app.modules.guides.service.get_storage", lambda: storage)
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        guide_id = (await _create(a, title="geheim"))["id"]
        att = (await _attach(a, guide_id, "s.pdf", b"top secret")).json()
        # B (other household) cannot see the attachment (RLS -> 404).
        assert (await b.get(f"/v1/guides/{guide_id}/attachments/{att['id']}")).status_code == 404
