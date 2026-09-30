"""End-to-end HTTP tests for messaging/Briefe (Testcontainers PG 18 + Redis): send, inbox, read
receipts, unread count, household isolation. Skipped without Docker."""

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


async def test_round_letter_read_flow(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        # Admin sends a round-letter (to_ids empty -> everyone).
        sent = await admin.post(
            "/v1/letters",
            json={"subject": "Hausputz", "body_md": "Samstag 10 Uhr"},
            headers=_csrf(admin),
        )
        assert sent.status_code == 201, sent.text
        letter_id = sent.json()["id"]

        # The member sees it unread.
        assert (await member.get("/v1/letters/unread-count")).json()["unread"] == 1
        inbox = (await member.get("/v1/letters")).json()
        mine = next(letter for letter in inbox if letter["id"] == letter_id)
        assert mine["read_by_me"] is False
        assert mine["read_count"] == 0

        # Opening it marks it read (idempotent) and counts once.
        opened = await member.get(f"/v1/letters/{letter_id}")
        assert opened.json()["read_by_me"] is True
        assert opened.json()["body_md"] == "Samstag 10 Uhr"
        await member.get(f"/v1/letters/{letter_id}")  # second open does not double-count
        assert (await member.get("/v1/letters/unread-count")).json()["unread"] == 0
        reread = (await member.get("/v1/letters")).json()
        assert next(letter for letter in reread if letter["id"] == letter_id)["read_count"] == 1


async def test_sender_sees_own_letter_but_it_is_not_unread(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        sent = await admin.post("/v1/letters", json={"subject": "Notiz"}, headers=_csrf(admin))
        letter_id = sent.json()["id"]
        # The author's own letter shows in their inbox but never counts as unread.
        inbox = (await admin.get("/v1/letters")).json()
        assert any(letter["id"] == letter_id for letter in inbox)
        assert (await admin.get("/v1/letters/unread-count")).json()["unread"] == 0
        # Opening own letter does not create a read receipt.
        assert (await admin.get(f"/v1/letters/{letter_id}")).json()["read_count"] == 0


async def test_addressed_letter_only_targets_recipient(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        member_id = await _join_member(admin, member)
        # Admin addresses the letter only to the member.
        await admin.post(
            "/v1/letters",
            json={"subject": "Für dich", "to_ids": [member_id]},
            headers=_csrf(admin),
        )
        assert (await member.get("/v1/letters/unread-count")).json()["unread"] == 1


async def test_convert_letter_to_task(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        member_id = await _join_member(admin, member)
        await admin.post(
            "/v1/letters",
            json={"subject": "Müll rausbringen", "to_ids": [member_id]},
            headers=_csrf(admin),
        )
        letter_id = (await member.get("/v1/letters")).json()[0]["id"]
        # The recipient takes it on -> a personal task assigned to them.
        resp = await member.post(f"/v1/letters/{letter_id}/to-task", headers=_csrf(member))
        assert resp.status_code == 201, resp.text
        assert resp.json()["title"] == "Müll rausbringen"
        tasks = (await member.get("/v1/tasks/instances")).json()
        task = next(t for t in tasks if t["title"] == "Müll rausbringen")
        assert task["points"] == 0
        assert task["assigned_to"] == member_id
        # Non-destructive: the letter stays.
        assert (await member.get(f"/v1/letters/{letter_id}")).status_code == 200


async def test_convert_missing_letter_is_404(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.post(f"/v1/letters/{uuid.uuid4()}/to-task", headers=_csrf(admin))
        assert resp.status_code == 404


async def test_foreign_letter_is_404(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        a_letter = (
            await a.post("/v1/letters", json={"subject": "privat"}, headers=_csrf(a))
        ).json()["id"]
        assert (await b.get(f"/v1/letters/{a_letter}")).status_code == 404
