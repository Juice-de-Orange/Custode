"""End-to-end HTTP tests for recipes CRUD (Testcontainers Postgres 18 + Redis). Register -> create
household -> recipe create/get/list/patch(If-Match)/delete. Skipped without Docker; the Postgres
and Redis fixtures come from conftest.py."""

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


async def _admin_household(client: AsyncClient) -> None:
    """Register a user and create a household (caller becomes admin in it)."""
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    reg = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Koch"},
    )
    assert reg.status_code == 201, reg.text
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text


async def test_recipe_crud_and_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post(
            "/v1/recipes",
            json={"title": "Pasta", "servings": 2, "ingredients": [{"raw_text": "500g Mehl"}]},
            headers=_csrf(c),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        recipe_id = body["id"]
        etag = created.headers["etag"]
        assert body["ingredients"][0]["raw_text"] == "500g Mehl"

        # list + get
        assert any(r["id"] == recipe_id for r in (await c.get("/v1/recipes")).json())
        got = await c.get(f"/v1/recipes/{recipe_id}")
        assert got.status_code == 200
        assert got.headers["etag"] == etag

        # patch with the current ETag bumps the version
        patched = await c.patch(
            f"/v1/recipes/{recipe_id}",
            json={"title": "Pasta neu", "servings": 4},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert patched.status_code == 200
        assert patched.json()["title"] == "Pasta neu"
        assert patched.headers["etag"] != etag

        # a stale ETag is refused
        stale = await c.patch(
            f"/v1/recipes/{recipe_id}",
            json={"title": "X"},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert stale.status_code == 412
        assert stale.json()["type"].endswith("precondition_failed")

        # soft-delete -> gone
        assert (await c.delete(f"/v1/recipes/{recipe_id}", headers=_csrf(c))).status_code == 204
        assert (await c.get(f"/v1/recipes/{recipe_id}")).status_code == 404


async def test_recipe_requires_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post("/v1/recipes", json={"title": "Suppe"}, headers=_csrf(c))
        recipe_id = created.json()["id"]
        resp = await c.patch(
            f"/v1/recipes/{recipe_id}", json={"title": "Andere Suppe"}, headers=_csrf(c)
        )
        assert resp.status_code == 428
        assert resp.json()["type"].endswith("precondition_required")


_RECIPE_LD = (
    '<script type="application/ld+json">'
    '{"@type":"Recipe","name":"Importiert","recipeYield":"3",'
    '"recipeIngredient":["1 Apfel"],"recipeInstructions":"Schälen."}'
    "</script>"
)


async def test_recipe_import_returns_draft(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str) -> tuple[str, str]:
        return url, f"<html><head>{_RECIPE_LD}</head></html>"

    monkeypatch.setattr("app.modules.recipes.service.safe_fetch", fake_fetch)
    async with _client(app) as c:
        await _admin_household(c)
        resp = await c.post(
            "/v1/recipes/import", json={"url": "https://example.com/r"}, headers=_csrf(c)
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["title"] == "Importiert"
        assert body["servings"] == 3
        assert body["ingredients"][0]["raw_text"] == "1 Apfel"
        assert body["source_url"] == "https://example.com/r"
        # the draft is not persisted — the user must save it explicitly
        assert (await c.get("/v1/recipes")).json() == []


async def test_recipe_import_no_recipe(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(url: str) -> tuple[str, str]:
        return url, "<html><body>kein Rezept</body></html>"

    monkeypatch.setattr("app.modules.recipes.service.safe_fetch", fake_fetch)
    async with _client(app) as c:
        await _admin_household(c)
        resp = await c.post(
            "/v1/recipes/import", json={"url": "https://example.com/x"}, headers=_csrf(c)
        )
        assert resp.status_code == 422
        assert resp.json()["type"].endswith("import_no_recipe")


async def test_ingredients_search(app: FastAPI) -> None:
    """The canonical-ingredient corpus (Migration 0017 seed) is searchable (nutrition module)."""
    async with _client(app) as c:
        await _admin_household(c)
        all_rows = await c.get("/v1/ingredients")
        assert all_rows.status_code == 200
        assert len(all_rows.json()) >= 20  # starter corpus is seeded
        filtered = await c.get("/v1/ingredients", params={"q": "mehl"})
        assert filtered.status_code == 200
        assert "Mehl" in [row["name_de"] for row in filtered.json()]


async def test_recipe_autolinks_ingredient(app: FastAPI) -> None:
    """Creating a recipe auto-maps its lines to the canonical corpus (recipes -> nutrition.api)."""
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post(
            "/v1/recipes",
            json={
                "title": "Brot",
                "ingredients": [{"raw_text": "250 g Mehl"}, {"raw_text": "etwas Xyzzy"}],
            },
            headers=_csrf(c),
        )
        assert created.status_code == 201, created.text
        by_text = {line["raw_text"]: line for line in created.json()["ingredients"]}
        assert by_text["250 g Mehl"]["ingredient_name"] == "Mehl"
        assert by_text["250 g Mehl"]["ingredient_id"] is not None
        assert by_text["etwas Xyzzy"]["ingredient_name"] is None  # no canonical match


async def test_recipe_nutrition_endpoint(app: FastAPI) -> None:
    """GET /v1/recipes/{id}/nutrition computes per-portion values from the matched ingredients."""
    async with _client(app) as c:
        await _admin_household(c)
        created = await c.post(
            "/v1/recipes",
            json={
                "title": "Mehlspeise",
                "servings": 2,
                "ingredients": [{"raw_text": "200 g Mehl"}],
            },
            headers=_csrf(c),
        )
        recipe_id = created.json()["id"]
        resp = await c.get(f"/v1/recipes/{recipe_id}/nutrition")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        # Mehl 364 kcal/100 g * 200 g = 728 total / 2 servings = 364.
        assert body["kcal"] == 364.0
        assert body["confidence"] == "complete"
        assert body["total"] == 1


def _png_bytes() -> bytes:
    import io

    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (10, 10), "red").save(out, format="PNG")
    return out.getvalue()


async def test_recipe_photo_upload_get_delete(
    app: FastAPI, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.kernel.storage import FilesystemStorage

    storage = FilesystemStorage(tmp_path)
    monkeypatch.setattr("app.modules.recipes.router.get_storage", lambda: storage)
    monkeypatch.setattr("app.modules.recipes.service.get_storage", lambda: storage)
    async with _client(app) as c:
        await _admin_household(c)
        recipe_id = (await c.post("/v1/recipes", json={"title": "Foto"}, headers=_csrf(c))).json()[
            "id"
        ]

        up = await c.put(
            f"/v1/recipes/{recipe_id}/photo",
            files={"file": ("p.png", _png_bytes(), "image/png")},
            headers=_csrf(c),
        )
        assert up.status_code == 200, up.text
        assert up.json()["has_photo"] is True

        got = await c.get(f"/v1/recipes/{recipe_id}/photo")
        assert got.status_code == 200
        assert got.headers["content-type"] == "image/jpeg"
        assert got.content[:2] == b"\xff\xd8"  # re-encoded JPEG (EXIF stripped)

        deleted = await c.delete(f"/v1/recipes/{recipe_id}/photo", headers=_csrf(c))
        assert deleted.status_code == 204
        assert (await c.get(f"/v1/recipes/{recipe_id}")).json()["has_photo"] is False


async def test_photo_upload_503_without_storage(app: FastAPI) -> None:
    # The default test env configures no storage_dir -> NullStorage -> uploads disabled (graceful).
    async with _client(app) as c:
        await _admin_household(c)
        recipe_id = (await c.post("/v1/recipes", json={"title": "X"}, headers=_csrf(c))).json()[
            "id"
        ]
        resp = await c.put(
            f"/v1/recipes/{recipe_id}/photo",
            files={"file": ("p.png", _png_bytes(), "image/png")},
            headers=_csrf(c),
        )
        assert resp.status_code == 503
