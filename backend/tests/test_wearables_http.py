"""End-to-end HTTP tests for wearables (P9-S5, Testcontainers PG 18 + Redis).

Covers what the RLS test cannot: the role guard (children/guests out), the unauthenticated OAuth
callback with its state single-use and role re-check, consent grant/revoke incl. the "last type
withdrawn disconnects" invariant, the hard delete, both Graceful-Enhancement paths, and that no
token ever reaches a response or a log.

Skipped without Docker.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from urllib.parse import parse_qs, urlparse

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.kernel.crypto import generate_key
from app.kernel.ports.wearable import WearableAuthError, WearableTokens
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"
_ACCESS_TOKEN = "oura-access-token-geheim"  # the secret that must never surface
_REFRESH_TOKEN = "oura-refresh-token-geheim"
_SLEEP = "wearable_sleep"
_ACTIVITY = "wearable_activity"
_HEARTRATE = "wearable_heartrate"


# ------------------------------------------------------------------ fake OAuth port


class FakeOAuth:
    """Recording fake port (E14) injected via ``app.state`` — the ``test_calendar_*_http``
    pattern. Fast, and it lets a test decide per case whether the exchange succeeds."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail_with: str | None = None

    def authorize_url(self, *, state: str, scopes: list[str], redirect_uri: str) -> str:
        return f"https://provider.example/authorize?state={state}&scope={'+'.join(scopes)}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> WearableTokens:
        self.calls.append((code, redirect_uri))
        if self.fail_with:
            raise WearableAuthError(self.fail_with)
        return WearableTokens(
            access_token=_ACCESS_TOKEN,
            refresh_token=_REFRESH_TOKEN,
            scopes=["daily", "heartrate"],
        )

    async def refresh(self, *, refresh_token: str) -> WearableTokens:
        raise WearableAuthError("refresh_failed")


# ------------------------------------------------------------------ infrastructure fixtures


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


@pytest.fixture(autouse=True)
def no_ambient_crypto_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keyless is the deterministic default; tests opt in via ``crypto_key``."""
    monkeypatch.delenv("CUSTODE_CRYPTO_KEY", raising=False)
    get_settings.cache_clear()


@pytest.fixture
def crypto_key(db: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setenv("CUSTODE_CRYPTO_KEY", generate_key())
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("CUSTODE_CRYPTO_KEY", raising=False)
    get_settings.cache_clear()


@pytest.fixture
def oauth() -> FakeOAuth:
    return FakeOAuth()


@pytest.fixture
def app(db: None, redis_db: None, oauth: FakeOAuth) -> FastAPI:
    instance = create_app()
    instance.state.wearable_oauth = oauth
    return instance


@pytest.fixture(autouse=True)
def pwned_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _zero(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr("app.modules.accounts.service.pwned_count", _zero)


def _client(app_obj: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app_obj), base_url="http://test")


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(_CSRF)
    return {"X-CSRF-Token": token} if token else {}


# ------------------------------------------------------------------ domain helpers


async def _sql(pg: PgDatabase, query: str, *args: object) -> object:
    conn = await asyncpg.connect(
        host=pg.get_container_host_ip(),
        port=int(pg.get_exposed_port(5432)),
        user=pg.username,
        password=pg.password,
        database=pg.dbname,
    )
    try:
        return await conn.fetchval(query, *args)
    finally:
        await conn.close()


async def _enable_flag(pg: PgDatabase) -> None:
    """Turn the ``wearables`` flag on for every household (default is off)."""
    await _sql(
        pg,
        "UPDATE households SET settings_json = "
        "coalesce(settings_json, '{}'::jsonb) || '{\"wearables\": true}'::jsonb;",
    )


async def _admin_household(client: AsyncClient) -> str:
    email = f"u{uuid.uuid4().hex[:12]}@example.de"
    await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Admin"},
    )
    created = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert created.status_code == 201, created.text
    return str((await client.get("/v1/auth/me")).json()["user_id"])


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
    return str((await member.get("/v1/auth/me")).json()["user_id"])


async def _child_client(app_obj: FastAPI, admin: AsyncClient) -> AsyncClient:
    household_id = (await admin.get("/v1/auth/me")).json()["household_id"]
    username = f"kind{uuid.uuid4().hex[:8]}"
    created = await admin.post(
        "/v1/household/children",
        json={"display_name": "Kind", "username": username, "pin": "1234"},
        headers=_csrf(admin),
    )
    assert created.status_code == 201, created.text
    child = _client(app_obj)
    logged_in = await child.post(
        "/v1/auth/child-login",
        json={"household_id": household_id, "username": username, "pin": "1234"},
    )
    assert logged_in.status_code == 200, logged_in.text
    return child


async def _connect(client: AsyncClient, oauth: FakeOAuth, types: list[str]) -> str:
    """Run the full authorize → callback flow, return the connection id."""
    started = await client.post(
        "/v1/wearables/oura/authorize",
        json={"consent_types": types},
        headers=_csrf(client),
    )
    assert started.status_code == 200, started.text
    state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]
    done = await client.get(
        "/v1/wearables/oura/callback", params={"code": "the-code", "state": state}
    )
    assert done.status_code == 302, done.text
    assert "connected=oura" in done.headers["location"]
    listed = await client.get("/v1/wearables/connections")
    assert listed.status_code == 200, listed.text
    return str(listed.json()[0]["id"])


# ------------------------------------------------------------------ role guard


async def test_child_is_refused_on_every_route(app: FastAPI, pg: PgDatabase) -> None:
    """Root-CLAUDE.md: keine Wearables für Kinder-Accounts."""
    async with _client(app) as admin:
        await _admin_household(admin)
        await _enable_flag(pg)
        child = await _child_client(app, admin)
        try:
            assert (await child.get("/v1/wearables/connections")).status_code == 403
            assert (
                await child.post(
                    "/v1/wearables/oura/authorize",
                    json={"consent_types": [_SLEEP]},
                    headers=_csrf(child),
                )
            ).status_code == 403
            assert (
                await child.delete(
                    f"/v1/wearables/connections/{uuid.uuid4()}", headers=_csrf(child)
                )
            ).status_code == 403
        finally:
            await child.aclose()


async def test_foreign_connection_is_404_even_for_an_admin(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    """N-2: health data is member-private. An admin gets the same 404 as a stranger — the
    response must not even confirm that the connection exists."""
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        await _enable_flag(pg)
        connection_id = await _connect(member, oauth, [_SLEEP])

        assert (await admin.get("/v1/wearables/connections")).json() == []
        patched = await admin.patch(
            f"/v1/wearables/connections/{connection_id}/consents",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(admin),
        )
        assert patched.status_code == 404
        deleted = await admin.delete(
            f"/v1/wearables/connections/{connection_id}", headers=_csrf(admin)
        )
        assert deleted.status_code == 404


# ------------------------------------------------------------------ happy path


async def test_connect_stores_ciphertext_and_records_consent(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    async with _client(app) as client:
        user_id = await _admin_household(client)
        await _enable_flag(pg)
        connection_id = await _connect(client, oauth, [_SLEEP, _HEARTRATE])

        body = (await client.get("/v1/wearables/connections")).json()[0]
        assert body["has_tokens"] is True
        assert body["consent_types"] == [_SLEEP, _HEARTRATE]
        assert body["status"] == "active"
        # Write-only: no token, no refresh token, no ciphertext on the wire.
        serialised = str(body)
        assert _ACCESS_TOKEN not in serialised
        assert _REFRESH_TOKEN not in serialised
        assert "tokens_enc" not in body

        stored = await _sql(
            pg,
            "SELECT tokens_enc FROM wearable_connections WHERE id = $1;",
            uuid.UUID(connection_id),
        )
        assert isinstance(stored, str)
        assert stored.startswith("v1:")  # SecretBox scheme prefix (ADR-0077)
        assert _ACCESS_TOKEN not in stored
        assert _REFRESH_TOKEN not in stored

        granted = await _sql(
            pg,
            "SELECT count(*) FROM consents WHERE subject_user_id = $1 AND action = 'grant' "
            "AND type LIKE 'wearable_%';",
            uuid.UUID(user_id),
        )
        assert granted == 2


async def test_authorize_requests_only_the_scopes_the_types_need(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        started = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        # Sleep needs only ``daily`` — consenting to sleep must not request heart rate.
        assert "heartrate" not in started.json()["authorize_url"]


async def test_second_connection_is_rejected(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        await _connect(client, oauth, [_SLEEP])
        again = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        assert again.status_code == 409
        assert again.json()["type"].endswith("#connection_exists")


async def test_unknown_consent_type_is_rejected(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    """A typo must fail loudly, not silently consent to nothing."""
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        answer = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": ["wearable_bloodpressure"]},
            headers=_csrf(client),
        )
        assert answer.status_code == 422


# ------------------------------------------------------------------ callback edge cases


async def test_state_is_single_use(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    """A replayed callback must not mint a second connection."""
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        started = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]
        first = await client.get(
            "/v1/wearables/oura/callback", params={"code": "c1", "state": state}
        )
        assert "connected=oura" in first.headers["location"]
        replay = await client.get(
            "/v1/wearables/oura/callback", params={"code": "c2", "state": state}
        )
        assert "error=state_invalid" in replay.headers["location"]
        assert len((await client.get("/v1/wearables/connections")).json()) == 1


async def test_unknown_state_creates_nothing(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        answer = await client.get(
            "/v1/wearables/oura/callback", params={"code": "c", "state": "fabricated"}
        )
        assert "error=state_invalid" in answer.headers["location"]
        assert (await client.get("/v1/wearables/connections")).json() == []


async def test_provider_denial_creates_nothing(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        answer = await client.get("/v1/wearables/oura/callback", params={"error": "access_denied"})
        assert "error=denied" in answer.headers["location"]
        assert (await client.get("/v1/wearables/connections")).json() == []


async def test_failed_exchange_creates_nothing(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        started = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]
        oauth.fail_with = "exchange_failed"
        answer = await client.get(
            "/v1/wearables/oura/callback", params={"code": "c", "state": state}
        )
        assert "error=exchange_failed" in answer.headers["location"]
        assert (await client.get("/v1/wearables/connections")).json() == []


async def test_callback_never_leaks_the_code_or_state(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        started = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]
        answer = await client.get(
            "/v1/wearables/oura/callback", params={"code": "sensitive-code", "state": state}
        )
        location = answer.headers["location"]
        assert "sensitive-code" not in location
        assert state not in location
        assert _ACCESS_TOKEN not in location


async def test_role_is_rechecked_after_the_consent_screen(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    """Up to ten minutes pass on the provider's screen. If the account was demoted to child in
    the meantime, the callback must refuse — the route guard cannot help, the request carries no
    authenticated principal."""
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        member_id = await _join_member(admin, member)
        await _enable_flag(pg)
        started = await member.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(member),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]

        await _sql(
            pg,
            "UPDATE memberships SET role = 'child' WHERE user_id = $1;",
            uuid.UUID(member_id),
        )
        answer = await member.get(
            "/v1/wearables/oura/callback", params={"code": "c", "state": state}
        )
        assert "error=forbidden" in answer.headers["location"]
        assert (
            await _sql(
                pg,
                "SELECT count(*) FROM wearable_connections WHERE member_id = $1;",
                uuid.UUID(member_id),
            )
            == 0
        )


# ------------------------------------------------------------------ consent changes


async def test_withdrawing_a_type_erases_its_values(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    async with _client(app) as client:
        user_id = await _admin_household(client)
        await _enable_flag(pg)
        connection_id = await _connect(client, oauth, [_SLEEP, _ACTIVITY])
        household_id = (await client.get("/v1/auth/me")).json()["household_id"]

        # Simulate a 9-S6 ingest run so the purge has something to erase.
        await _sql(
            pg,
            "INSERT INTO wearable_daily (household_id, member_id, provider, day, sleep_score, "
            "steps) VALUES ($1, $2, 'oura', CURRENT_DATE, 80, 5000);",
            uuid.UUID(household_id),
            uuid.UUID(user_id),
        )

        patched = await client.patch(
            f"/v1/wearables/connections/{connection_id}/consents",
            json={"consent_types": [_SLEEP]},  # activity withdrawn
            headers=_csrf(client),
        )
        assert patched.status_code == 200
        assert patched.json()["consent_types"] == [_SLEEP]

        # Sleep survives, activity is gone — Art. 9 "delete button that really deletes".
        assert (
            await _sql(
                pg,
                "SELECT sleep_score FROM wearable_daily WHERE member_id = $1;",
                uuid.UUID(user_id),
            )
            == 80
        )
        assert (
            await _sql(
                pg, "SELECT steps FROM wearable_daily WHERE member_id = $1;", uuid.UUID(user_id)
            )
            is None
        )
        assert (
            await _sql(
                pg,
                "SELECT count(*) FROM consents WHERE subject_user_id = $1 AND action = 'revoke';",
                uuid.UUID(user_id),
            )
            == 1
        )


async def test_withdrawing_the_last_type_disconnects(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    """A connection with no consented type has no legal basis — it must not linger as an inert
    row."""
    async with _client(app) as client:
        user_id = await _admin_household(client)
        await _enable_flag(pg)
        connection_id = await _connect(client, oauth, [_SLEEP])

        patched = await client.patch(
            f"/v1/wearables/connections/{connection_id}/consents",
            json={"consent_types": []},
            headers=_csrf(client),
        )
        assert patched.status_code == 200
        assert patched.json() is None
        assert (await client.get("/v1/wearables/connections")).json() == []
        assert (
            await _sql(
                pg,
                "SELECT count(*) FROM wearable_connections WHERE member_id = $1;",
                uuid.UUID(user_id),
            )
            == 0
        )


async def test_delete_is_hard_and_keeps_the_consent_trail(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    async with _client(app) as client:
        user_id = await _admin_household(client)
        await _enable_flag(pg)
        connection_id = await _connect(client, oauth, [_SLEEP])

        deleted = await client.delete(
            f"/v1/wearables/connections/{connection_id}", headers=_csrf(client)
        )
        assert deleted.status_code == 204
        # Hard delete, no tombstone (the table has a CHECK against one).
        assert (
            await _sql(
                pg,
                "SELECT count(*) FROM wearable_connections WHERE member_id = $1;",
                uuid.UUID(user_id),
            )
            == 0
        )
        assert (
            await _sql(
                pg,
                "SELECT count(*) FROM wearable_daily WHERE member_id = $1;",
                uuid.UUID(user_id),
            )
            == 0
        )
        # The append-only ledger keeps the record that consent existed and was withdrawn.
        assert (
            await _sql(
                pg,
                "SELECT count(*) FROM consents WHERE subject_user_id = $1 AND action = 'revoke';",
                uuid.UUID(user_id),
            )
            == 1
        )


# ------------------------------------------------------------------ graceful enhancement


async def test_without_a_crypto_key_connecting_is_503_but_reading_and_deleting_work(
    app: FastAPI, pg: PgDatabase, oauth: FakeOAuth
) -> None:
    """ADR-0077: no key → the dependent feature is off, never a crash. Deleting must keep
    working regardless — a member has to be able to get rid of their health data."""
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        blocked = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        assert blocked.status_code == 503
        assert blocked.json()["type"].endswith("#crypto_unconfigured")

        assert (await client.get("/v1/wearables/connections")).status_code == 200
        gone = await client.delete(
            f"/v1/wearables/connections/{uuid.uuid4()}", headers=_csrf(client)
        )
        assert gone.status_code == 404  # reached the handler, not a 503


async def test_with_the_provider_switched_off_connecting_is_503(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    """Kill switch / missing operator credentials → Null adapter, which refuses."""
    from app.adapters.null import NullWearableOAuth

    app.state.wearable_oauth = NullWearableOAuth()
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        blocked = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        assert blocked.status_code == 503
        assert blocked.json()["type"].endswith("#wearables_disabled")
        assert (await client.get("/v1/wearables/connections")).status_code == 200


async def test_flag_off_blocks_connecting_but_not_reading(app: FastAPI, crypto_key: None) -> None:
    """The ``wearables`` flag defaults to OFF — and it is enforced server-side, not only by a
    hidden UI element."""
    async with _client(app) as client:
        await _admin_household(client)  # deliberately NOT enabling the flag
        blocked = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        assert blocked.status_code == 403
        assert blocked.json()["type"].endswith("#feature_disabled")
        assert (await client.get("/v1/wearables/connections")).status_code == 200


async def test_writes_require_csrf(app: FastAPI, pg: PgDatabase, crypto_key: None) -> None:
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        answer = await client.post("/v1/wearables/oura/authorize", json={"consent_types": [_SLEEP]})
        assert answer.status_code == 403


# --- callback must be bound to the BROWSER, not just to the state (BUGLOG 2026-07-30) --------


async def test_a_foreign_browser_cannot_complete_my_flow(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    """The attack this closes: an attacker starts a connect flow and sends the authorize URL to
    somebody else. That person consents with THEIR provider account, and without a browser check
    their tokens land in the ATTACKER's row — the attacker then reads the victim's Art.-9 health
    data as if it were their own.

    The single-use state authenticates the FLOW; it says nothing about who presents it."""
    async with _client(app) as attacker, _client(app) as victim:
        await _admin_household(attacker)
        await _join_member(attacker, victim)
        await _enable_flag(pg)

        started = await attacker.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(attacker),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]

        # The victim's browser follows the link and consents at the provider.
        answer = await victim.get(
            "/v1/wearables/oura/callback", params={"code": "victim-code", "state": state}
        )
        assert "error=state_invalid" in answer.headers["location"]

        # Nothing was created for either party.
        assert (await attacker.get("/v1/wearables/connections")).json() == []
        assert (await victim.get("/v1/wearables/connections")).json() == []
        assert oauth.calls == []  # the code was never even exchanged


async def test_a_session_less_browser_cannot_complete_a_flow(
    app: FastAPI, pg: PgDatabase, crypto_key: None
) -> None:
    """No session = we cannot attribute the grant, so we refuse. Same answer as a mismatch, so
    the response never reveals whether a state existed."""
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        started = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]

        async with _client(app) as anonymous:  # a fresh client carries no cookies
            answer = await anonymous.get(
                "/v1/wearables/oura/callback", params={"code": "c", "state": state}
            )
        assert "error=state_invalid" in answer.headers["location"]
        assert (await client.get("/v1/wearables/connections")).json() == []


async def test_state_is_consumed_atomically(
    app: FastAPI, pg: PgDatabase, crypto_key: None, oauth: FakeOAuth
) -> None:
    """Two callbacks arriving together must not both see the payload. With GET-then-DELETE they
    would, and "single-use" would quietly mean "usable twice"."""

    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        started = await client.post(
            "/v1/wearables/oura/authorize",
            json={"consent_types": [_SLEEP]},
            headers=_csrf(client),
        )
        state = parse_qs(urlparse(started.json()["authorize_url"]).query)["state"][0]

        first, second = await asyncio.gather(
            client.get("/v1/wearables/oura/callback", params={"code": "a", "state": state}),
            client.get("/v1/wearables/oura/callback", params={"code": "b", "state": state}),
        )
        locations = [first.headers["location"], second.headers["location"]]
        assert sum("connected=oura" in loc for loc in locations) == 1
        assert sum("error=state_invalid" in loc for loc in locations) == 1
        assert len((await client.get("/v1/wearables/connections")).json()) == 1


async def test_no_token_or_code_reaches_the_logs(
    app: FastAPI,
    pg: PgDatabase,
    crypto_key: None,
    oauth: FakeOAuth,
    captured_logs: list[dict[str, object]],
) -> None:
    """This module's docstring promised it; until now nothing checked it."""
    async with _client(app) as client:
        await _admin_household(client)
        await _enable_flag(pg)
        await _connect(client, oauth, [_SLEEP])

    blob = repr(captured_logs)
    assert _ACCESS_TOKEN not in blob
    assert _REFRESH_TOKEN not in blob
    assert "the-code" not in blob
