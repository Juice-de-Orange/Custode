"""End-to-end HTTP tests for the Betreiber-Konsole auth (Testcontainers PG 18 + Redis): operator
login with mandatory TOTP, bearer-guarded /ops/me + /ops/health, wrong TOTP and missing token. The
app reads operators via the ops_readonly connection. Skipped without Docker."""

from __future__ import annotations

import base64
import os
import uuid
from collections.abc import AsyncIterator

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from soft_webauthn import SoftWebauthnDevice
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.kernel.db.engine as engine_mod
from app.kernel.auth import totp
from app.kernel.auth.passwords import hash_password
from app.main import create_app
from app.modules.backoffice import service as operator_service
from app.settings import get_settings
from conftest import PgDatabase


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    keys = (
        "CUSTODE_DATABASE_URL",
        "CUSTODE_DATABASE_URL_MAINT",
        "CUSTODE_DATABASE_URL_OPS",
        "CUSTODE_DATABASE_URL_OPS_ACTIONS",
    )
    prev = {k: os.environ.get(k) for k in keys}
    os.environ["CUSTODE_DATABASE_URL"] = (
        f"postgresql+asyncpg://custode_app:app@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_MAINT"] = (
        f"postgresql+asyncpg://custode_maint:maint@{host}:{port}/{pg.dbname}"
    )
    os.environ["CUSTODE_DATABASE_URL_OPS"] = (
        f"postgresql+asyncpg://ops_readonly:ops@{host}:{port}/{pg.dbname}"
    )
    # Audited write actions (banners, flags, audit_log) run on the ops_actions role. Without its own
    # URL the engine would fall back to custode_app (read-only on ops tables -> permission denied);
    # without a per-test reset its asyncpg pool leaks across event loops ("different loop").
    os.environ["CUSTODE_DATABASE_URL_OPS_ACTIONS"] = (
        f"postgresql+asyncpg://ops_actions:ops_act@{host}:{port}/{pg.dbname}"
    )
    get_settings.cache_clear()
    engine_mod._engine = engine_mod._sessionmaker = None
    engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
    engine_mod._ops_engine = engine_mod._ops_sessionmaker = None
    engine_mod._ops_actions_engine = engine_mod._ops_actions_sessionmaker = None
    try:
        yield
    finally:
        for eng in (
            engine_mod._engine,
            engine_mod._maint_engine,
            engine_mod._ops_engine,
            engine_mod._ops_actions_engine,
        ):
            if eng is not None:
                await eng.dispose()
        engine_mod._engine = engine_mod._sessionmaker = None
        engine_mod._maint_engine = engine_mod._maint_sessionmaker = None
        engine_mod._ops_engine = engine_mod._ops_sessionmaker = None
        engine_mod._ops_actions_engine = engine_mod._ops_actions_sessionmaker = None
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


_SECRET = totp.generate_secret()
_OP_EMAIL = "ops@example.de"
_OP_PASSWORD = "ein-sehr-sicheres-operator-passwort"


async def _seed_operator(pg: PgDatabase) -> None:
    su = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await su.execute("DELETE FROM operators;")
        await su.execute(
            "INSERT INTO operators "
            "(id, email, password_hash, totp_secret, totp_enabled, is_active) "
            "VALUES ($1,$2,$3,$4,true,true);",
            uuid.uuid4(),
            _OP_EMAIL,
            hash_password(_OP_PASSWORD),
            _SECRET,
        )
    finally:
        await su.close()


_OP2_EMAIL = "ops2@example.de"


async def _seed_two_operators(pg: PgDatabase) -> uuid.UUID:
    """Seed the primary operator + a second one (no TOTP, active); returns the second's id."""
    op2 = uuid.uuid4()
    su = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await su.execute("DELETE FROM operators;")
        await su.execute(
            "INSERT INTO operators "
            "(id, email, password_hash, totp_secret, totp_enabled, is_active) VALUES "
            "($1,$2,$3,$4,true,true), ($5,$6,$7,NULL,false,true);",
            uuid.uuid4(),
            _OP_EMAIL,
            hash_password(_OP_PASSWORD),
            _SECRET,
            op2,
            _OP2_EMAIL,
            hash_password("op2-password-not-used-in-this-test"),
        )
    finally:
        await su.close()
    return op2


async def test_operator_login_me_health(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    async with _client(app) as client:
        login = await client.post(
            "/ops/auth/login",
            json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
        )
        assert login.status_code == 200, login.text
        token = login.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        me = await client.get("/ops/me", headers=auth)
        assert me.status_code == 200
        assert me.json()["email"] == _OP_EMAIL

        health = await client.get("/ops/health", headers=auth)
        assert health.status_code == 200
        assert "git_sha" in health.json()

        # KPIs come from the aggregate views (ops_readonly). At least the seeded operator's
        # household-less state: counters present, no crash, no fact-table access needed.
        kpis = await client.get("/ops/kpis", headers=auth)
        assert kpis.status_code == 200
        body = kpis.json()
        assert set(body["usage"]) == {"households", "users", "adult_members", "children"}
        assert isinstance(body["daily"], list)

        logout = await client.post("/ops/auth/logout", headers=auth)
        assert logout.status_code == 204
        # Session revoked: the token no longer authenticates.
        assert (await client.get("/ops/me", headers=auth)).status_code == 401


async def _audit_count(pg: PgDatabase, action: str) -> int:
    su = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        return int(await su.fetchval("SELECT count(*) FROM audit_log WHERE action = $1;", action))
    finally:
        await su.close()


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get("custode_csrf")
    return {"X-CSRF-Token": token} if token else {}


async def test_operator_banner_lifecycle_is_audited(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    async with _client(app) as client:
        token = (
            await client.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            "/ops/banners",
            json={"message": "Wartung heute 22 Uhr", "level": "warning"},
            headers=auth,
        )
        assert created.status_code == 201, created.text
        banner_id = created.json()["id"]
        assert created.json()["is_active"] is True
        assert await _audit_count(pg, "banner.created") == 1

        listed = await client.get("/ops/banners", headers=auth)
        assert banner_id in [b["id"] for b in listed.json()]

        off = await client.post(f"/ops/banners/{banner_id}/deactivate", headers=auth)
        assert off.status_code == 200
        assert off.json()["is_active"] is False
        assert await _audit_count(pg, "banner.deactivated") == 1


async def test_app_member_sees_active_banner(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    async with _client(app) as client:
        token = (
            await client.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        await client.post(
            "/ops/banners",
            json={"message": "Hallo Haushalt", "level": "info"},
            headers={"Authorization": f"Bearer {token}"},
        )

    async with _client(app) as member:
        email = f"u{uuid.uuid4().hex[:12]}@example.de"
        await member.post(
            "/v1/auth/register",
            json={"email": email, "password": "ein-sehr-sicheres-passwort", "display_name": "M"},
        )
        await member.post("/v1/households", json={"name": "Fam"}, headers=_csrf(member))
        banners = await member.get("/v1/banners")
        assert banners.status_code == 200
        assert "Hallo Haushalt" in [b["message"] for b in banners.json()]


async def test_operator_global_flag_audited_and_reflected_in_me(
    app: FastAPI, pg: PgDatabase
) -> None:
    await _seed_operator(pg)
    async with _client(app) as ops:
        token = (
            await ops.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        flags = await ops.get("/ops/flags", headers=auth)
        assert flags.status_code == 200
        assert "wearables" in flags.json()["available"]

        set_resp = await ops.put("/ops/flags/wearables", json={"enabled": True}, headers=auth)
        assert set_resp.status_code == 200
        assert set_resp.json()["overrides"]["wearables"] is True
        assert await _audit_count(pg, "flag.changed") == 1

        # Unknown flag -> 422.
        assert (
            await ops.put("/ops/flags/not-a-flag", json={"enabled": True}, headers=auth)
        ).status_code == 422

    async with _client(app) as member:
        email = f"u{uuid.uuid4().hex[:12]}@example.de"
        await member.post(
            "/v1/auth/register",
            json={"email": email, "password": "ein-sehr-sicheres-passwort", "display_name": "M"},
        )
        me = await member.get("/v1/auth/me")
        assert me.status_code == 200
        # The operator's global override flips the default-off wearables flag on.
        assert me.json()["flags"]["wearables"] is True


async def test_operator_support_search_metadata_only(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    # A real household for the operator to find.
    async with _client(app) as member:
        email = f"u{uuid.uuid4().hex[:12]}@example.de"
        await member.post(
            "/v1/auth/register",
            json={"email": email, "password": "ein-sehr-sicheres-passwort", "display_name": "M"},
        )
        created = await member.post(
            "/v1/households", json={"name": "Suchbar GmbH"}, headers=_csrf(member)
        )
        household_id = created.json()["household_id"]

    async with _client(app) as ops:
        token = (
            await ops.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        found = await ops.get("/ops/households", params={"q": "Suchbar"}, headers=auth)
        assert found.status_code == 200
        match = [h for h in found.json() if h["id"] == household_id]
        assert match and match[0]["name"] == "Suchbar GmbH"
        assert match[0]["member_count"] == 1 and match[0]["admin_count"] == 1
        # Metadata only — no household content fields leak.
        assert set(match[0]) == {"id", "name", "created_at", "member_count", "admin_count"}

        detail = await ops.get(f"/ops/households/{household_id}", headers=auth)
        assert detail.status_code == 200 and detail.json()["id"] == household_id
        assert (await ops.get(f"/ops/households/{uuid.uuid4()}", headers=auth)).status_code == 404

        # Sensitive reads are audited (ADR-0073). The 404 view raises before the audit, so exactly
        # one household.viewed is recorded (not two); the search records no PII (length/count only).
        assert await _audit_count(pg, "household.searched") == 1
        assert await _audit_count(pg, "household.viewed") == 1


async def test_operator_reads_feedback_inbox(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    # A household submits feedback.
    async with _client(app) as member:
        email = f"u{uuid.uuid4().hex[:12]}@example.de"
        await member.post(
            "/v1/auth/register",
            json={"email": email, "password": "ein-sehr-sicheres-passwort", "display_name": "M"},
        )
        await member.post("/v1/households", json={"name": "Fam"}, headers=_csrf(member))
        sent = await member.post(
            "/v1/feedback",
            json={"category": "bug", "message": "Etwas klemmt", "error_ref": "REF-9"},
            headers=_csrf(member),
        )
        assert sent.status_code == 201

    async with _client(app) as ops:
        token = (
            await ops.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        inbox = await ops.get("/ops/feedback", headers=auth)
        assert inbox.status_code == 200
        entry = [f for f in inbox.json() if f["message"] == "Etwas klemmt"]
        assert entry and entry[0]["category"] == "bug" and entry[0]["error_ref"] == "REF-9"
        # Category filter narrows it.
        ideas = await ops.get("/ops/feedback", params={"category": "idea"}, headers=auth)
        assert all(f["message"] != "Etwas klemmt" for f in ideas.json())

        # Both inbox reads are audited (ADR-0073): category filter + count only, no message content.
        assert await _audit_count(pg, "feedback.inbox.viewed") == 2


async def test_operator_audit_trail_read(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    async with _client(app) as ops:
        token = (
            await ops.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}

        # An audited action produces a trail entry (newest first).
        created = await ops.post(
            "/ops/banners", json={"message": "Wartung", "level": "info"}, headers=auth
        )
        assert created.status_code == 201

        trail = await ops.get("/ops/audit", headers=auth)
        assert trail.status_code == 200
        assert "banner.created" in [e["action"] for e in trail.json()]
        # PII-free contract: only structured fields, no free content.
        entry = next(e for e in trail.json() if e["action"] == "banner.created")
        assert set(entry) == {
            "id",
            "occurred_at",
            "actor_type",
            "actor_id",
            "action",
            "target_type",
            "target_id",
            "household_id",
            "detail",
            "request_id",
        }
        assert entry["actor_type"] == "operator"

        # Filter by exact action narrows the result.
        filtered = await ops.get("/ops/audit", params={"action": "banner.created"}, headers=auth)
        assert filtered.status_code == 200
        assert filtered.json() and all(e["action"] == "banner.created" for e in filtered.json())

        # Reading the trail is deliberately NOT itself audited (PII-free, no recursion/noise).
        assert await _audit_count(pg, "audit.viewed") == 0

    # AuthZ negative: without a bearer token the trail is 401 (fail-closed).
    async with _client(app) as anon:
        assert (await anon.get("/ops/audit")).status_code == 401


async def test_operator_management_list_toggle_and_self_guard(app: FastAPI, pg: PgDatabase) -> None:
    op2 = await _seed_two_operators(pg)
    async with _client(app) as ops:
        token = (
            await ops.post(
                "/ops/auth/login",
                json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
            )
        ).json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        my_id = (await ops.get("/ops/me", headers=auth)).json()["id"]

        # List shows both operators — summary fields only (no password_hash/totp_secret leak).
        listed = (await ops.get("/ops/operators", headers=auth)).json()
        assert {o["email"] for o in listed} == {_OP_EMAIL, _OP2_EMAIL}
        assert all(
            set(o) == {"id", "email", "totp_enabled", "is_active", "created_at"} for o in listed
        )

        # An operator cannot deactivate itself (409, lockout guard) — not audited.
        self_off = await ops.post(f"/ops/operators/{my_id}/deactivate", headers=auth)
        assert self_off.status_code == 409

        # Deactivate the second operator (audited); a repeat is an idempotent no-op (no new audit).
        off = await ops.post(f"/ops/operators/{op2}/deactivate", headers=auth)
        assert off.status_code == 200 and off.json()["is_active"] is False
        assert await _audit_count(pg, "operator.deactivated") == 1
        again = await ops.post(f"/ops/operators/{op2}/deactivate", headers=auth)
        assert again.status_code == 200 and again.json()["is_active"] is False
        assert await _audit_count(pg, "operator.deactivated") == 1  # unchanged (idempotent)

        # Reactivate (audited); repeat is again an idempotent no-op.
        on = await ops.post(f"/ops/operators/{op2}/reactivate", headers=auth)
        assert on.status_code == 200 and on.json()["is_active"] is True
        assert await _audit_count(pg, "operator.activated") == 1
        assert (await ops.post(f"/ops/operators/{op2}/reactivate", headers=auth)).status_code == 200
        assert await _audit_count(pg, "operator.activated") == 1  # unchanged (idempotent)

        # Unknown operator -> 404.
        unknown = await ops.post(f"/ops/operators/{uuid.uuid4()}/deactivate", headers=auth)
        assert unknown.status_code == 404


def _ops_actions_maker(pg: PgDatabase) -> async_sessionmaker[AsyncSession]:
    host = pg.get_container_host_ip()
    port = int(pg.get_exposed_port(5432))
    engine = create_async_engine(
        f"postgresql+asyncpg://ops_actions:ops_act@{host}:{port}/{pg.dbname}"
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_deactivating_last_active_operator_is_refused(pg: PgDatabase) -> None:
    """The last-active guard (prevents the lockout race). With op2 the only active operator,
    deactivating it raises rather than reaching zero active operators."""
    op2 = await _seed_two_operators(pg)
    # Leave op2 the only active operator (simulates a concurrent deactivation of the primary).
    su = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        await su.execute("UPDATE operators SET is_active = false WHERE email = $1;", _OP_EMAIL)
    finally:
        await su.close()

    maker = _ops_actions_maker(pg)
    async with maker() as session:
        with pytest.raises(operator_service.LastActiveOperatorError):
            await operator_service.set_operator_active(
                session, operator_id=op2, active=False, actor_id=uuid.uuid4()
            )


async def test_operator_login_rejects_wrong_totp_and_missing_token(
    app: FastAPI, pg: PgDatabase
) -> None:
    await _seed_operator(pg)
    async with _client(app) as client:
        bad = await client.post(
            "/ops/auth/login",
            json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": "000000"},
        )
        assert bad.status_code == 401
        # No bearer token -> guarded routes are 401.
        assert (await client.get("/ops/me")).status_code == 401
        assert (await client.get("/ops/health")).status_code == 401


# ------------------------------------------------------------------------- operator passkeys


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64u(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def _ops_token(client: AsyncClient) -> str:
    resp = await client.post(
        "/ops/auth/login",
        json={"email": _OP_EMAIL, "password": _OP_PASSWORD, "totp_code": totp.now(_SECRET)},
    )
    return str(resp.json()["token"])


async def _ops_register_passkey(
    client: AsyncClient, dev: SoftWebauthnDevice, token: str, name: str = "YubiKey"
) -> None:
    auth = {"Authorization": f"Bearer {token}"}
    opts = (await client.post("/ops/auth/passkeys/register/begin", headers=auth)).json()["options"]
    create_opts = {
        "publicKey": {
            "challenge": _unb64u(opts["challenge"]),
            "rp": {"id": opts["rp"]["id"], "name": opts["rp"]["name"]},
            "user": {
                "id": _unb64u(opts["user"]["id"]),
                "name": opts["user"]["name"],
                "displayName": opts["user"]["displayName"],
            },
            "pubKeyCredParams": [
                {"alg": p["alg"], "type": "public-key"} for p in opts["pubKeyCredParams"]
            ],
            "attestation": "none",
        }
    }
    att = dev.create(create_opts, "http://test")
    credential = {
        "id": _b64u(att["rawId"]),
        "rawId": _b64u(att["rawId"]),
        "response": {
            "clientDataJSON": _b64u(att["response"]["clientDataJSON"]),
            "attestationObject": _b64u(att["response"]["attestationObject"]),
        },
        "type": "public-key",
        "clientExtensionResults": {},
    }
    resp = await client.post(
        "/ops/auth/passkeys/register/complete",
        json={"credential": credential, "name": name},
        headers=auth,
    )
    assert resp.status_code == 204, resp.text


async def _ops_login_passkey(client: AsyncClient, dev: SoftWebauthnDevice) -> object:
    begin = (await client.post("/ops/auth/passkeys/login/begin")).json()
    opts, flow_id = begin["options"], begin["flow_id"]
    get_opts = {"publicKey": {"rpId": opts["rpId"], "challenge": _unb64u(opts["challenge"])}}
    asr = dev.get(get_opts, "http://test")
    credential = {
        "id": _b64u(asr["rawId"]),
        "rawId": _b64u(asr["rawId"]),
        "response": {
            "clientDataJSON": _b64u(asr["response"]["clientDataJSON"]),
            "authenticatorData": _b64u(asr["response"]["authenticatorData"]),
            "signature": _b64u(asr["response"]["signature"]),
            "userHandle": _b64u(asr["response"]["userHandle"]),
        },
        "type": "public-key",
        "clientExtensionResults": {},
    }
    # Cookieless: flow_id travels in the body, not a cookie.
    return await client.post(
        "/ops/auth/passkeys/login/complete", json={"credential": credential, "flow_id": flow_id}
    )


async def test_operator_passkey_register_and_passwordless_login(
    app: FastAPI, pg: PgDatabase
) -> None:
    await _seed_operator(pg)
    dev = SoftWebauthnDevice()
    async with _client(app) as ops:
        token = await _ops_token(ops)
        auth = {"Authorization": f"Bearer {token}"}
        await _ops_register_passkey(ops, dev, token)
        pks = (await ops.get("/ops/passkeys", headers=auth)).json()
        assert len(pks) == 1 and pks[0]["name"] == "YubiKey"

    # Passwordless login on a fresh client (no bearer) mints a session for the same operator.
    async with _client(app) as fresh:
        resp = await _ops_login_passkey(fresh, dev)
        assert resp.status_code == 200, resp.text
        new_token = resp.json()["token"]
        me = await fresh.get("/ops/me", headers={"Authorization": f"Bearer {new_token}"})
        assert me.status_code == 200 and me.json()["email"] == _OP_EMAIL


async def test_operator_passkey_delete_and_register_requires_auth(
    app: FastAPI, pg: PgDatabase
) -> None:
    await _seed_operator(pg)
    dev = SoftWebauthnDevice()
    async with _client(app) as ops:
        # register/begin without a bearer -> 401.
        assert (await ops.post("/ops/auth/passkeys/register/begin")).status_code == 401

        token = await _ops_token(ops)
        auth = {"Authorization": f"Bearer {token}"}
        await _ops_register_passkey(ops, dev, token)
        pid = (await ops.get("/ops/passkeys", headers=auth)).json()[0]["id"]

        deleted = await ops.delete(f"/ops/passkeys/{pid}", headers=auth)
        assert deleted.status_code == 204
        assert (await ops.get("/ops/passkeys", headers=auth)).json() == []
        # Deleting again -> 404.
        assert (await ops.delete(f"/ops/passkeys/{pid}", headers=auth)).status_code == 404


async def test_operator_passkey_login_rejects_unknown_flow(app: FastAPI, pg: PgDatabase) -> None:
    await _seed_operator(pg)
    async with _client(app) as client:
        # A completion with a flow_id that was never issued -> 400 (challenge expired/unknown).
        resp = await client.post(
            "/ops/auth/passkeys/login/complete",
            json={
                "credential": {"id": "AAAA", "rawId": "AAAA", "type": "public-key"},
                "flow_id": "nope",
            },
        )
        assert resp.status_code == 400
