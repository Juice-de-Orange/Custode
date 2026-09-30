"""End-to-end HTTP tests for comments (Testcontainers PG 18 + Redis): post, thread order, object
scoping, author-only delete, household isolation. Skipped without Docker."""

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


async def _join_member(admin: AsyncClient, member: AsyncClient) -> str:
    invite = await admin.post(
        "/v1/household/invites", json={"role": "member"}, headers=_csrf(admin)
    )
    code = invite.json()["code"]
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await member.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Mit"},
    )
    joined = await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
    assert joined.status_code == 201, joined.text
    return (await member.get("/v1/auth/me")).json()["user_id"]


async def test_post_list_and_thread_order(app: FastAPI) -> None:
    async with _client(app) as admin:
        user_id = await _admin_household(admin)
        obj = str(uuid.uuid4())
        for text in ("erst", "dann"):
            resp = await admin.post(
                "/v1/comments",
                json={"object_type": "guide", "object_id": obj, "body_md": text},
                headers=_csrf(admin),
            )
            assert resp.status_code == 201, resp.text
            assert resp.json()["author_id"] == user_id
        thread = (
            await admin.get("/v1/comments", params={"object_type": "guide", "object_id": obj})
        ).json()
        assert [c["body_md"] for c in thread] == ["erst", "dann"]  # oldest first


async def test_comments_are_scoped_to_their_object(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        a, b = str(uuid.uuid4()), str(uuid.uuid4())
        await admin.post(
            "/v1/comments",
            json={"object_type": "recipe", "object_id": a, "body_md": "on A"},
            headers=_csrf(admin),
        )
        on_b = await admin.get("/v1/comments", params={"object_type": "recipe", "object_id": b})
        assert on_b.json() == []  # different object_id -> empty thread


async def test_only_author_can_delete(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        obj = str(uuid.uuid4())
        comment_id = (
            await admin.post(
                "/v1/comments",
                json={"object_type": "task", "object_id": obj, "body_md": "meins"},
                headers=_csrf(admin),
            )
        ).json()["id"]
        # A housemate cannot delete someone else's comment.
        forbidden = await member.delete(f"/v1/comments/{comment_id}", headers=_csrf(member))
        assert forbidden.status_code == 403
        # The author can.
        ok = await admin.delete(f"/v1/comments/{comment_id}", headers=_csrf(admin))
        assert ok.status_code == 204
        gone = await admin.get("/v1/comments", params={"object_type": "task", "object_id": obj})
        assert gone.json() == []


async def test_author_can_edit_with_if_match(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        obj = str(uuid.uuid4())
        created = await admin.post(
            "/v1/comments",
            json={"object_type": "guide", "object_id": obj, "body_md": "tippfeler"},
            headers=_csrf(admin),
        )
        assert created.status_code == 201
        comment_id = created.json()["id"]
        version = created.json()["version"]
        assert created.headers["ETag"] == f'"{version}"'
        # Edit under the current version.
        patched = await admin.patch(
            f"/v1/comments/{comment_id}",
            json={"body_md": "tippfehler"},
            headers={**_csrf(admin), "If-Match": f'"{version}"'},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["body_md"] == "tippfehler"
        assert patched.json()["version"] > version
        # The thread reflects the edit (and the bumped version is carried inline).
        thread = (
            await admin.get("/v1/comments", params={"object_type": "guide", "object_id": obj})
        ).json()
        assert thread[0]["body_md"] == "tippfehler"


async def test_edit_with_stale_if_match_is_412(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        obj = str(uuid.uuid4())
        created = await admin.post(
            "/v1/comments",
            json={"object_type": "guide", "object_id": obj, "body_md": "a"},
            headers=_csrf(admin),
        )
        comment_id = created.json()["id"]
        version = created.json()["version"]
        # First edit moves the version forward.
        await admin.patch(
            f"/v1/comments/{comment_id}",
            json={"body_md": "b"},
            headers={**_csrf(admin), "If-Match": f'"{version}"'},
        )
        # Re-using the now-stale version is rejected (optimistic concurrency).
        stale = await admin.patch(
            f"/v1/comments/{comment_id}",
            json={"body_md": "c"},
            headers={**_csrf(admin), "If-Match": f'"{version}"'},
        )
        assert stale.status_code == 412


async def test_only_author_can_edit(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        obj = str(uuid.uuid4())
        created = await admin.post(
            "/v1/comments",
            json={"object_type": "task", "object_id": obj, "body_md": "meins"},
            headers=_csrf(admin),
        )
        comment_id = created.json()["id"]
        version = created.json()["version"]
        forbidden = await member.patch(
            f"/v1/comments/{comment_id}",
            json={"body_md": "fremd"},
            headers={**_csrf(member), "If-Match": f'"{version}"'},
        )
        assert forbidden.status_code == 403


async def test_foreign_comment_thread_is_isolated(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        obj = str(uuid.uuid4())
        await a.post(
            "/v1/comments",
            json={"object_type": "guide", "object_id": obj, "body_md": "geheim"},
            headers=_csrf(a),
        )
        # B (other household) sees nothing on the same object_id (RLS).
        on_obj = await b.get("/v1/comments", params={"object_type": "guide", "object_id": obj})
        assert on_obj.json() == []
