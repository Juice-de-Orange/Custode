"""End-to-end HTTP tests for vault (Testcontainers PG 18 + Redis): wrapped-key envelope round-trip,
encrypted-item CRUD with ETag/If-Match, summary hides the ciphertext, children are excluded (403),
and households are isolated. The server only ever stores/returns opaque ciphertext. Skipped without
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
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Admin"},
    )
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return created.json()["household_id"]


async def test_envelope_round_trip_and_idempotent(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        passphrase = await admin.put(
            "/v1/vault/keys",
            json={
                "kind": "passphrase",
                "wrapped_key": "d3JhcHBlZA==",
                "wrap_meta": {"kdf": "argon2id", "salt": "c2FsdA=="},
            },
            headers=_csrf(admin),
        )
        assert passphrase.status_code == 200, passphrase.text
        assert passphrase.json()["wrap_meta"]["kdf"] == "argon2id"
        # A recovery envelope is household-wide (member_id NULL).
        recovery = await admin.put(
            "/v1/vault/keys",
            json={"kind": "recovery", "wrapped_key": "cmVjb3Zlcg=="},
            headers=_csrf(admin),
        )
        assert recovery.status_code == 200, recovery.text
        assert recovery.json()["member_id"] is None

        keys = (await admin.get("/v1/vault/keys")).json()
        assert {k["kind"] for k in keys} == {"passphrase", "recovery"}

        # Re-storing the passphrase envelope replaces it (idempotent, still one).
        await admin.put(
            "/v1/vault/keys",
            json={"kind": "passphrase", "wrapped_key": "bmV3"},
            headers=_csrf(admin),
        )
        keys2 = (await admin.get("/v1/vault/keys")).json()
        passphrases = [k for k in keys2 if k["kind"] == "passphrase"]
        assert len(passphrases) == 1
        assert passphrases[0]["wrapped_key"] == "bmV3"


async def test_item_crud_with_etag_and_summary_hides_ciphertext(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        created = await admin.post(
            "/v1/vault/items",
            json={"ciphertext": "c2VjcmV0", "item_meta": {"nonce": "bm9uY2U="}},
            headers=_csrf(admin),
        )
        assert created.status_code == 201, created.text
        assert created.headers["ETag"] == '"1"'
        item_id = created.json()["id"]

        # The list summary carries the encrypted meta but NOT the secret ciphertext.
        listed = (await admin.get("/v1/vault/items")).json()
        assert [i["id"] for i in listed] == [item_id]
        assert "ciphertext" not in listed[0]
        assert listed[0]["item_meta"] == {"nonce": "bm9uY2U="}

        # Fetching one returns the ciphertext + ETag.
        fetched = await admin.get(f"/v1/vault/items/{item_id}")
        assert fetched.json()["ciphertext"] == "c2VjcmV0"
        etag = fetched.headers["ETag"]

        # PATCH under If-Match rotates the ciphertext and bumps the version.
        patched = await admin.patch(
            f"/v1/vault/items/{item_id}",
            json={"ciphertext": "bmV3c2VjcmV0"},
            headers={**_csrf(admin), "If-Match": etag},
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["ciphertext"] == "bmV3c2VjcmV0"
        assert patched.headers["ETag"] == '"2"'

        # A stale If-Match is rejected (412).
        stale = await admin.patch(
            f"/v1/vault/items/{item_id}",
            json={"ciphertext": "eA=="},
            headers={**_csrf(admin), "If-Match": etag},
        )
        assert stale.status_code == 412

        deleted = await admin.delete(f"/v1/vault/items/{item_id}", headers=_csrf(admin))
        assert deleted.status_code == 204
        assert (await admin.get(f"/v1/vault/items/{item_id}")).status_code == 404


async def test_children_are_excluded(app: FastAPI) -> None:
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
            # Children have no vault access at all (Root-CLAUDE.md).
            assert (await child.get("/v1/vault/items")).status_code == 403
            assert (await child.get("/v1/vault/keys")).status_code == 403


async def test_vault_is_isolated_across_households(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _admin_household(a)
        await _admin_household(b)
        await a.post(
            "/v1/vault/items",
            json={"ciphertext": "Z2VoZWlt"},
            headers=_csrf(a),
        )
        # B (other household) sees none of A's secrets (RLS).
        assert (await b.get("/v1/vault/items")).json() == []
