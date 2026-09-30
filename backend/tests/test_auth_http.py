"""End-to-end HTTP tests for the accounts auth + household surface (Testcontainers
Postgres 18 + Redis). Drives the real ASGI app: opaque cookie sessions, refresh
rotation + theft revoke, double-submit CSRF, and the household create/invite/join/
switch/role flow incl. RLS isolation. Skipped without Docker.

Cookie names are the dev (non-``__Host-``) variants; ``settings.env`` defaults to dev,
so cookies are not ``Secure`` and round-trip over http://test."""

from __future__ import annotations

import base64
import os
import re
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from soft_webauthn import SoftWebauthnDevice

import app.kernel.db.engine as engine_mod
from app.kernel.auth import totp
from app.kernel.ports.mail import get_mail
from app.main import create_app
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_AT = "custode_at"
_RT = "custode_rt"
_CSRF = "custode_csrf"


def _email() -> str:
    return f"u{uuid.uuid4().hex[:12]}@example.de"


@pytest.fixture
async def db(pg: PgDatabase) -> AsyncIterator[None]:
    """Repoint both the app (custode_app) and maint (custode_maint) engines."""
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


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with _client(app) as ac:
        yield ac


@pytest.fixture(autouse=True)
def pwned_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: the password is not breached (no real HIBP call). Tests that want the
    breached path override this."""

    async def _zero(*_a: object, **_k: object) -> int:
        return 0

    monkeypatch.setattr("app.modules.accounts.service.pwned_count", _zero)


def _csrf(client: AsyncClient) -> dict[str, str]:
    token = client.cookies.get(_CSRF)
    return {"X-CSRF-Token": token} if token else {}


async def _register(client: AsyncClient, email: str | None = None) -> tuple[str, dict[str, object]]:
    email = email or _email()
    resp = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Tester"},
    )
    assert resp.status_code == 201, resp.text
    return email, resp.json()


# --------------------------------------------------------------------------- auth


async def test_register_sets_cookies_and_me(api: AsyncClient) -> None:
    email, body = await _register(api)
    assert body["household_id"] is None
    assert api.cookies.get(_AT)
    assert api.cookies.get(_RT)
    assert api.cookies.get(_CSRF)

    me = await api.get("/v1/auth/me")
    assert me.status_code == 200
    data = me.json()
    assert data["email"] == email
    assert data["household_id"] is None
    assert data["role"] is None


async def test_login_cookie_flags(api: AsyncClient) -> None:
    email, _ = await _register(api)
    resp = await api.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert resp.status_code == 200
    cookies = resp.headers.get_list("set-cookie")
    access = next(c for c in cookies if c.startswith(f"{_AT}="))
    assert "HttpOnly" in access
    assert "SameSite=lax" in access
    assert "Path=/" in access


async def test_register_weak_password(api: AsyncClient) -> None:
    resp = await api.post(
        "/v1/auth/register",
        json={"email": _email(), "password": "kurz", "display_name": "X"},
    )
    assert resp.status_code == 422
    assert resp.json()["type"].endswith("weak_password")


async def test_register_pwned_password(api: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def _breached(*_a: object, **_k: object) -> int:
        return 7

    monkeypatch.setattr("app.modules.accounts.service.pwned_count", _breached)
    resp = await api.post(
        "/v1/auth/register",
        json={"email": _email(), "password": _PASSWORD, "display_name": "X"},
    )
    assert resp.status_code == 422
    assert resp.json()["type"].endswith("pwned_password")


async def test_register_duplicate_email(api: AsyncClient) -> None:
    email = _email()
    await _register(api, email)
    resp = await api.post(
        "/v1/auth/register",
        json={"email": email, "password": _PASSWORD, "display_name": "Again"},
    )
    assert resp.status_code == 409
    assert resp.json()["type"].endswith("email_taken")


async def test_login_wrong_password(api: AsyncClient) -> None:
    email, _ = await _register(api)
    resp = await api.post("/v1/auth/login", json={"email": email, "password": "ganz-falsch-123"})
    assert resp.status_code == 401
    assert resp.json()["type"].endswith("invalid_credentials")


async def test_me_unauthenticated(api: AsyncClient) -> None:
    resp = await api.get("/v1/auth/me")
    assert resp.status_code == 401


async def test_me_forged_cookie(app: FastAPI) -> None:
    async with _client(app) as c:
        c.cookies.set(_AT, "nicht-echt")
        resp = await c.get("/v1/auth/me")
    assert resp.status_code == 401


async def test_refresh_rotates(api: AsyncClient) -> None:
    await _register(api)
    old_rt = api.cookies.get(_RT)
    resp = await api.post("/v1/auth/refresh", headers=_csrf(api))
    assert resp.status_code == 200
    assert api.cookies.get(_RT) != old_rt
    assert (await api.get("/v1/auth/me")).status_code == 200


async def test_refresh_reuse_revokes_family(app: FastAPI) -> None:
    async with _client(app) as first:
        await _register(first)
        old_rt = first.cookies.get(_RT)
        csrf = first.cookies.get(_CSRF)
        rotated = await first.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert rotated.status_code == 200
    # Replay the consumed refresh token on a fresh client -> theft signal.
    async with _client(app) as c:
        c.cookies.set(_RT, old_rt, path="/v1/auth")
        c.cookies.set(_CSRF, csrf)
        resp = await c.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 401
    assert resp.json()["type"].endswith("token_reuse")


async def test_reuse_burns_victims_live_access_without_requester_cookie(app: FastAPI) -> None:
    # The victim logs in, then rotates once -> it now holds a *fresh, live* access token
    # (the one minted at register was revoked by that rotation; this one is current).
    async with _client(app) as victim:
        await _register(victim)
        consumed_rt = victim.cookies.get(_RT)
        csrf = victim.cookies.get(_CSRF)
        rot = await victim.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert rot.status_code == 200
        victim_at = victim.cookies.get(_AT)
        assert (await victim.get("/v1/auth/me")).status_code == 200
    # The attacker replays the *consumed* refresh token with NO access cookie -> theft.
    async with _client(app) as attacker:
        attacker.cookies.set(_RT, consumed_rt, path="/v1/auth")
        attacker.cookies.set(_CSRF, csrf)
        resp = await attacker.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 401
        assert resp.json()["type"].endswith("token_reuse")
    # The victim's still-live access token must now be dead in Redis — an instant kill,
    # even though the attacker never presented it. (Regression: the family burn used to be
    # gated on the caller's own access cookie, so this token survived for up to the TTL.)
    async with _client(app) as check:
        check.cookies.set(_AT, victim_at)
        assert (await check.get("/v1/auth/me")).status_code == 401


async def test_csrf_required_on_refresh(api: AsyncClient) -> None:
    await _register(api)
    missing = await api.post("/v1/auth/refresh")
    assert missing.status_code == 403
    assert missing.json()["type"].endswith("csrf_failed")
    wrong = await api.post("/v1/auth/refresh", headers={"X-CSRF-Token": "falsch"})
    assert wrong.status_code == 403


async def test_logout_clears_and_blocks(api: AsyncClient) -> None:
    await _register(api)
    old_rt = api.cookies.get(_RT)
    csrf = api.cookies.get(_CSRF)
    out = await api.post("/v1/auth/logout")
    assert out.status_code == 204
    assert (await api.get("/v1/auth/me")).status_code == 401
    resp = await api.post(
        "/v1/auth/refresh",
        cookies={_RT: old_rt, _CSRF: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 401


async def test_logout_without_session_is_204(api: AsyncClient) -> None:
    assert (await api.post("/v1/auth/logout")).status_code == 204


# Die vier Cookie-Kombinationen des Logouts (11-B3). Bis dahin hingen seine zwei Wirkungen an
# zwei verschiedenen Cookies — mit verschiedenen Pfaden und verschiedenen Lebensdauern —, und
# getestet waren nur die beiden symmetrischen Faelle: "beide da" und "gar keine". Die zwei
# dazwischen sind genau die, in denen die Abmeldung halb blieb.


async def test_logout_with_only_the_refresh_cookie_still_burns_the_access_tokens(
    app: FastAPI,
) -> None:
    """Ohne Access-Cookie blieb Redis stehen.

    Der Fall ist der Normalfall nach einer Pause: das Access-Cookie laeuft nach 15 Minuten ab,
    das Refresh-Cookie lebt 30 Tage. Wer sich danach abmeldet, schickte bis 11-B3 nur das
    Refresh-Cookie — die Sitzung wurde widerrufen, aber ``access_family:<fam>`` und
    ``active_household:<fam>`` blieben liegen.
    """
    async with _client(app) as user:
        await _register(user)
        access_token = user.cookies.get(_AT)
        refresh_token = user.cookies.get(_RT)
        csrf = user.cookies.get(_CSRF)
        assert (await user.get("/v1/auth/me")).status_code == 200, "Vorher: die Sitzung traegt"

    async with _client(app) as only_refresh:
        only_refresh.cookies.set(_RT, refresh_token, path="/v1/auth")
        only_refresh.cookies.set(_CSRF, csrf)
        assert (await only_refresh.post("/v1/auth/logout")).status_code == 204

    async with _client(app) as check:
        check.cookies.set(_AT, access_token)
        assert (await check.get("/v1/auth/me")).status_code == 401


async def test_logout_with_only_the_access_cookie_still_revokes_the_session(app: FastAPI) -> None:
    """Der ernstere Spiegelfall: ohne Refresh-Cookie lebte die **Sitzung** weiter.

    Redis wurde verbrannt, ``auth_sessions.revoked_at`` blieb NULL — die Abmeldung sah vollstaendig
    aus, und das Refresh-Token holte die Sitzung jederzeit zurueck. Das Refresh-Cookie ist auf
    ``/v1/auth`` gescopt; ein Client, der ``/v1/auth/logout`` ueber einen Proxy oder aus einer
    anderen Origin anspricht, schickt es nicht zwangslaeufig mit.
    """
    async with _client(app) as user:
        await _register(user)
        access_token = user.cookies.get(_AT)
        refresh_token = user.cookies.get(_RT)
        csrf = user.cookies.get(_CSRF)

    async with _client(app) as only_access:
        only_access.cookies.set(_AT, access_token)
        assert (await only_access.post("/v1/auth/logout")).status_code == 204

    # Die Gegenprobe, die den Fehler sichtbar macht: das Refresh-Token darf die Sitzung nicht
    # zurueckholen koennen. Vorher lieferte diese Rotation ein frisches Token-Paar.
    async with _client(app) as revive:
        revive.cookies.set(_RT, refresh_token, path="/v1/auth")
        revive.cookies.set(_CSRF, csrf)
        resp = await revive.post("/v1/auth/refresh", headers={"X-CSRF-Token": csrf})
        assert resp.status_code == 401, "Die Sitzung muss beendet sein, nicht nur die Tokens"


# ---------------------------------------------------------------------- households


async def test_create_household_makes_admin(api: AsyncClient) -> None:
    await _register(api)
    resp = await api.post("/v1/households", json={"name": "WG Sonnenhof"}, headers=_csrf(api))
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "admin"
    me = (await api.get("/v1/auth/me")).json()
    assert me["household_id"] == body["household_id"]
    assert me["role"] == "admin"


async def test_list_households(api: AsyncClient) -> None:
    await _register(api)
    created = (await api.post("/v1/households", json={"name": "Liste"}, headers=_csrf(api))).json()
    listing = await api.get("/v1/households")
    assert listing.status_code == 200
    ids = [h["household_id"] for h in listing.json()]
    assert created["household_id"] in ids


async def test_invite_and_join_flow(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as guest:
        await _register(admin)
        household = (
            await admin.post("/v1/households", json={"name": "Familie"}, headers=_csrf(admin))
        ).json()
        invite = await admin.post("/v1/household/invites", json={}, headers=_csrf(admin))
        assert invite.status_code == 201
        code = invite.json()["code"]

        await _register(guest)
        joined = await guest.post("/v1/households/join", json={"code": code}, headers=_csrf(guest))
        assert joined.status_code == 201
        assert joined.json()["household_id"] == household["household_id"]
        assert joined.json()["role"] == "member"
        guest_me = (await guest.get("/v1/auth/me")).json()
        assert guest_me["household_id"] == household["household_id"]


async def test_invite_requires_admin(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _register(admin)
        await admin.post("/v1/households", json={"name": "H"}, headers=_csrf(admin))
        code = (
            await admin.post("/v1/household/invites", json={"max_uses": 5}, headers=_csrf(admin))
        ).json()["code"]
        await _register(member)
        await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
        forbidden = await member.post("/v1/household/invites", json={}, headers=_csrf(member))
        assert forbidden.status_code == 403


async def test_double_join_conflicts(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as guest:
        await _register(admin)
        await admin.post("/v1/households", json={"name": "H"}, headers=_csrf(admin))
        code = (
            await admin.post("/v1/household/invites", json={"max_uses": 5}, headers=_csrf(admin))
        ).json()["code"]
        await _register(guest)
        first = await guest.post("/v1/households/join", json={"code": code}, headers=_csrf(guest))
        assert first.status_code == 201
        again = await guest.post("/v1/households/join", json={"code": code}, headers=_csrf(guest))
        assert again.status_code == 409
        assert again.json()["type"].endswith("already_member")


async def test_change_role(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        _, admin_body = await _register(admin)
        await admin.post("/v1/households", json={"name": "H"}, headers=_csrf(admin))
        code = (await admin.post("/v1/household/invites", json={}, headers=_csrf(admin))).json()[
            "code"
        ]
        _, member_body = await _register(member)
        await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))

        members = (await admin.get("/v1/household/members")).json()
        by_user = {m["user_id"]: m for m in members}
        assert admin_body["user_id"] in by_user
        assert member_body["user_id"] in by_user

        mem_id = by_user[member_body["user_id"]]["membership_id"]
        promote = await admin.patch(
            f"/v1/household/members/{mem_id}", json={"role": "admin"}, headers=_csrf(admin)
        )
        assert promote.status_code == 200
        assert promote.json()["role"] == "admin"


async def test_last_admin_cannot_be_demoted(app: FastAPI) -> None:
    async with _client(app) as admin:
        _, body = await _register(admin)
        await admin.post("/v1/households", json={"name": "Solo"}, headers=_csrf(admin))
        members = (await admin.get("/v1/household/members")).json()
        own = next(m for m in members if m["user_id"] == body["user_id"])
        resp = await admin.patch(
            f"/v1/household/members/{own['membership_id']}",
            json={"role": "member"},
            headers=_csrf(admin),
        )
        assert resp.status_code == 403


async def test_switch_household(app: FastAPI) -> None:
    async with _client(app) as api:
        await _register(api)
        h1 = (await api.post("/v1/households", json={"name": "Eins"}, headers=_csrf(api))).json()
        h2 = (await api.post("/v1/households", json={"name": "Zwei"}, headers=_csrf(api))).json()
        switched = await api.post(f"/v1/households/{h1['household_id']}/switch", headers=_csrf(api))
        assert switched.status_code == 200
        assert switched.json()["household_id"] == h1["household_id"]
        me = (await api.get("/v1/auth/me")).json()
        assert me["household_id"] == h1["household_id"]
        assert h2["household_id"] != h1["household_id"]


async def test_switch_non_member_forbidden(api: AsyncClient) -> None:
    await _register(api)
    await api.post("/v1/households", json={"name": "Mein"}, headers=_csrf(api))
    resp = await api.post(f"/v1/households/{uuid.uuid4()}/switch", headers=_csrf(api))
    assert resp.status_code == 403


async def test_members_rls_isolation(app: FastAPI) -> None:
    """A user in household A never sees household B's roster (RLS)."""
    async with _client(app) as a, _client(app) as b:
        await _register(a)
        await a.post("/v1/households", json={"name": "A"}, headers=_csrf(a))
        await _register(b)
        await b.post("/v1/households", json={"name": "B"}, headers=_csrf(b))
        a_members = (await a.get("/v1/household/members")).json()
        a_user_ids = {m["user_id"] for m in a_members}
        b_me = (await b.get("/v1/auth/me")).json()
        assert b_me["user_id"] not in a_user_ids
        assert len(a_members) == 1


async def test_fresh_login_scopes_to_sole_household(app: FastAPI) -> None:
    """A fresh login (new device) lands directly in the user's only household — no
    manual switch needed (P8 Prod-QA: a context-less session 403'd every screen)."""
    async with _client(app) as first:
        email, _ = await _register(first)
        created = (
            await first.post("/v1/households", json={"name": "Zuhause"}, headers=_csrf(first))
        ).json()

    async with _client(app) as fresh:
        login = await fresh.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
        assert login.status_code == 200
        assert login.json()["household_id"] == created["household_id"]
        assert login.json()["role"] == "admin"
        # Household-scoped endpoints work immediately, without an explicit switch.
        members = await fresh.get("/v1/household/members")
        assert members.status_code == 200
        # The scope survives a refresh (remembered as the family's active household).
        refreshed = await fresh.post("/v1/auth/refresh", headers=_csrf(fresh))
        assert refreshed.status_code == 200
        assert refreshed.json()["household_id"] == created["household_id"]


async def test_fresh_login_multi_household_stays_unscoped(app: FastAPI) -> None:
    """With several memberships the pick stays explicit — login must not guess."""
    async with _client(app) as first:
        email, _ = await _register(first)
        await first.post("/v1/households", json={"name": "Eins"}, headers=_csrf(first))
        await first.post("/v1/households", json={"name": "Zwei"}, headers=_csrf(first))

    async with _client(app) as fresh:
        login = await fresh.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
        assert login.status_code == 200
        assert login.json()["household_id"] is None
        assert login.json()["role"] is None


async def test_removed_member_cannot_switch_back(app: FastAPI) -> None:
    """A soft-deleted membership is dead for authorization: the removed member must not
    re-enter via switch (or see the household in the picker) while the 30-day reaper
    hasn't hard-deleted the row yet."""
    async with _client(app) as admin, _client(app) as member:
        await _register(admin)
        household = (
            await admin.post("/v1/households", json={"name": "H"}, headers=_csrf(admin))
        ).json()
        code = (await admin.post("/v1/household/invites", json={}, headers=_csrf(admin))).json()[
            "code"
        ]
        member_email, member_body = await _register(member)
        await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))

        members = (await admin.get("/v1/household/members")).json()
        mem_id = next(m["membership_id"] for m in members if m["user_id"] == member_body["user_id"])
        removed = await admin.delete(f"/v1/household/members/{mem_id}", headers=_csrf(admin))
        assert removed.status_code == 204

    async with _client(app) as back:
        login = await back.post(
            "/v1/auth/login", json={"email": member_email, "password": _PASSWORD}
        )
        assert login.status_code == 200
        # Not auto-scoped into the household they were removed from …
        assert login.json()["household_id"] is None
        # … absent from the picker …
        assert (await back.get("/v1/households")).json() == []
        # … and the explicit switch is refused.
        switch = await back.post(
            f"/v1/households/{household['household_id']}/switch", headers=_csrf(back)
        )
        assert switch.status_code == 403


# ----------------------------------------------------------------------------- totp


async def test_totp_enroll_login_disable(app: FastAPI) -> None:
    async with _client(app) as api:
        email, _ = await _register(api)
        setup = await api.post("/v1/auth/totp/setup", headers=_csrf(api))
        assert setup.status_code == 200
        secret = setup.json()["secret"]
        assert setup.json()["otpauth_uri"].startswith("otpauth://totp/")

        enable = await api.post(
            "/v1/auth/totp/enable", json={"code": totp.now(secret)}, headers=_csrf(api)
        )
        assert enable.status_code == 200
        assert len(enable.json()["recovery_codes"]) == 10
        assert (await api.get("/v1/auth/me")).json()["totp_enabled"] is True

        # login now requires the second factor
        no_code = await api.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
        assert no_code.status_code == 401
        assert no_code.json()["type"].endswith("totp_required")
        with_code = await api.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "totp_code": totp.now(secret)},
        )
        assert with_code.status_code == 200

        disable = await api.post(
            "/v1/auth/totp/disable", json={"code": totp.now(secret)}, headers=_csrf(api)
        )
        assert disable.status_code == 204
        assert (await api.get("/v1/auth/me")).json()["totp_enabled"] is False


async def test_totp_login_wrong_code(app: FastAPI) -> None:
    async with _client(app) as api:
        email, _ = await _register(api)
        secret = (await api.post("/v1/auth/totp/setup", headers=_csrf(api))).json()["secret"]
        await api.post("/v1/auth/totp/enable", json={"code": totp.now(secret)}, headers=_csrf(api))
        wrong = "111111" if totp.now(secret) != "111111" else "222222"
        resp = await api.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "totp_code": wrong},
        )
        assert resp.status_code == 401
        assert resp.json()["type"].endswith("totp_required")


async def test_totp_setup_conflict_when_enabled(app: FastAPI) -> None:
    async with _client(app) as api:
        await _register(api)
        secret = (await api.post("/v1/auth/totp/setup", headers=_csrf(api))).json()["secret"]
        await api.post("/v1/auth/totp/enable", json={"code": totp.now(secret)}, headers=_csrf(api))
        again = await api.post("/v1/auth/totp/setup", headers=_csrf(api))
        assert again.status_code == 409
        assert again.json()["type"].endswith("totp_already_enabled")


async def _enable_totp(api: AsyncClient) -> list[str]:
    secret = (await api.post("/v1/auth/totp/setup", headers=_csrf(api))).json()["secret"]
    enable = await api.post(
        "/v1/auth/totp/enable", json={"code": totp.now(secret)}, headers=_csrf(api)
    )
    return enable.json()["recovery_codes"]


async def test_recovery_code_login_and_single_use(app: FastAPI) -> None:
    async with _client(app) as api:
        email, _ = await _register(api)
        codes = await _enable_totp(api)
        assert len(codes) == 10
        assert (await api.get("/v1/auth/me")).json()["recovery_codes_remaining"] == 10

        # login with a recovery code, no TOTP code
        ok = await api.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "recovery_code": codes[0]},
        )
        assert ok.status_code == 200
        # same code cannot be reused
        again = await api.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "recovery_code": codes[0]},
        )
        assert again.status_code == 401
        assert again.json()["type"].endswith("totp_required")
        assert (await api.get("/v1/auth/me")).json()["recovery_codes_remaining"] == 9


async def test_recovery_codes_regenerate(app: FastAPI) -> None:
    async with _client(app) as api:
        email, _ = await _register(api)
        old = await _enable_totp(api)
        fresh = await api.post("/v1/auth/totp/recovery-codes", headers=_csrf(api))
        assert fresh.status_code == 200
        new_codes = fresh.json()["recovery_codes"]
        assert len(new_codes) == 10
        assert set(new_codes).isdisjoint(old)

        # an old code no longer works, a new one does
        bad = await api.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "recovery_code": old[0]},
        )
        assert bad.status_code == 401
        good = await api.post(
            "/v1/auth/login",
            json={"email": email, "password": _PASSWORD, "recovery_code": new_codes[0]},
        )
        assert good.status_code == 200


# ------------------------------------------------------------------------- passkeys


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64u(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def _register_passkey(
    api: AsyncClient, dev: SoftWebauthnDevice, name: str = "MacBook"
) -> None:
    opts = (await api.post("/v1/auth/passkeys/register/begin", headers=_csrf(api))).json()[
        "options"
    ]
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
    resp = await api.post(
        "/v1/auth/passkeys/register/complete",
        json={"credential": credential, "name": name},
        headers=_csrf(api),
    )
    assert resp.status_code == 204, resp.text


async def _login_passkey(client: AsyncClient, dev: SoftWebauthnDevice) -> object:
    opts = (await client.post("/v1/auth/passkeys/login/begin")).json()["options"]
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
    return await client.post("/v1/auth/passkeys/login/complete", json={"credential": credential})


async def test_passkey_register_and_passwordless_login(app: FastAPI) -> None:
    dev = SoftWebauthnDevice()
    async with _client(app) as api:
        email, _ = await _register(api)
        await _register_passkey(api, dev)
        pks = (await api.get("/v1/auth/passkeys")).json()
        assert len(pks) == 1
        assert pks[0]["name"] == "MacBook"
    # passwordless login on a fresh client (no password) -> a session for the same user
    async with _client(app) as fresh:
        resp = await _login_passkey(fresh, dev)
        assert resp.status_code == 200, resp.text
        me = await fresh.get("/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == email


async def test_passkey_delete(app: FastAPI) -> None:
    dev = SoftWebauthnDevice()
    async with _client(app) as api:
        await _register(api)
        await _register_passkey(api, dev)
        pid = (await api.get("/v1/auth/passkeys")).json()[0]["id"]
        resp = await api.delete(f"/v1/auth/passkeys/{pid}", headers=_csrf(api))
        assert resp.status_code == 204
        assert (await api.get("/v1/auth/passkeys")).json() == []


async def test_passkey_login_requires_flow(app: FastAPI) -> None:
    async with _client(app) as client:
        resp = await client.post(
            "/v1/auth/passkeys/login/complete",
            json={"credential": {"id": "x", "type": "public-key", "response": {}}},
        )
        assert resp.status_code == 400
        assert resp.json()["type"].endswith("passkey_challenge_expired")


# ------------------------------------------------------- sessions + login audit (S8b)


async def test_sessions_list_and_current_flag(app: FastAPI) -> None:
    async with _client(app) as c1:
        email, _ = await _register(c1)  # family A
        async with _client(app) as c2:
            # a second login for the same user starts a second family
            await c2.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
            sessions = (await c2.get("/v1/auth/sessions")).json()
            assert len(sessions) == 2
            current = [s for s in sessions if s["current"]]
            assert len(current) == 1  # only c2's own family is current from c2's view


async def test_revoke_session_kills_the_other_device(app: FastAPI) -> None:
    async with _client(app) as c1:
        email, _ = await _register(c1)  # family A, c1 authenticated
        assert (await c1.get("/v1/auth/me")).status_code == 200
        async with _client(app) as c2:
            await c2.post(
                "/v1/auth/login", json={"email": email, "password": _PASSWORD}
            )  # family B
            sessions = (await c2.get("/v1/auth/sessions")).json()
            other = next(s for s in sessions if not s["current"])  # family A
            resp = await c2.delete(f"/v1/auth/sessions/{other['family_id']}", headers=_csrf(c2))
            assert resp.status_code == 204
        # family A's access token is burned and its refresh family revoked
        assert (await c1.get("/v1/auth/me")).status_code == 401
        assert (await c1.post("/v1/auth/refresh", headers=_csrf(c1))).status_code == 401


async def test_revoke_session_cross_user_is_404(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _register(a)  # user A, family A
        await _register(b)  # user B, family B
        a_family = (await a.get("/v1/auth/sessions")).json()[0]["family_id"]
        # user B cannot see or revoke user A's family (RLS user-scoped)
        resp = await b.delete(f"/v1/auth/sessions/{a_family}", headers=_csrf(b))
        assert resp.status_code == 404
        assert (await a.get("/v1/auth/me")).status_code == 200  # A unaffected
        b_sessions = (await b.get("/v1/auth/sessions")).json()
        assert all(s["family_id"] != a_family for s in b_sessions)


async def test_login_events_listed_and_pii_free(app: FastAPI) -> None:
    async with _client(app) as c:
        email, _ = await _register(c)  # one success (auto-login)
        await c.post("/v1/auth/login", json={"email": email, "password": "ganz-falsch"})  # one fail
        events = (await c.get("/v1/auth/login-events")).json()
        assert len(events) >= 2
        # PII-free shape: country code only, never IP/e-mail/token
        assert set(events[0].keys()) == {"success", "country_code", "created_at"}
        assert any(e["success"] for e in events) and any(not e["success"] for e in events)


async def test_login_events_user_scoped(app: FastAPI) -> None:
    async with _client(app) as a, _client(app) as b:
        await _register(a)
        await _register(b)
        # each user sees only their own single (register) attempt — no cross-user leak
        assert len((await a.get("/v1/auth/login-events")).json()) == 1
        assert len((await b.get("/v1/auth/login-events")).json()) == 1


# ------------------------------------------------------- password reset (S9a)


class _CaptureMail:
    """Test mail adapter: records sends so a test can read the reset link/token from the body."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    async def send(self, *, to: str, subject: str, body_md: str) -> bool:
        self.sent.append((to, subject, body_md))
        return True


def _reset_token(body: str) -> str:
    match = re.search(r"token=([\w\-]+)", body)
    assert match is not None, body
    return match.group(1)


async def test_password_reset_flow(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        email, _ = await _register(c)
        mail.sent.clear()  # drop the registration verification mail (S9b)
        forgot = await c.post("/v1/auth/password/forgot", json={"email": email})
        assert forgot.status_code == 204
        assert len(mail.sent) == 1
        token = _reset_token(mail.sent[0][2])
        new_pw = "ein-frisches-sicheres-passwort"
        reset = await c.post("/v1/auth/password/reset", json={"token": token, "password": new_pw})
        assert reset.status_code == 204
        # the old password no longer works; the new one does
        old = await c.post("/v1/auth/login", json={"email": email, "password": _PASSWORD})
        assert old.status_code == 401
        new = await c.post("/v1/auth/login", json={"email": email, "password": new_pw})
        assert new.status_code == 200


async def test_password_forgot_no_enumeration(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        # unknown address: 204, no mail
        unknown = await c.post("/v1/auth/password/forgot", json={"email": "nobody@example.de"})
        assert unknown.status_code == 204
        assert mail.sent == []
        # known address: identical 204, one mail sent
        email, _ = await _register(c)
        mail.sent.clear()  # drop the registration verification mail (S9b)
        known = await c.post("/v1/auth/password/forgot", json={"email": email})
        assert known.status_code == 204
        assert len(mail.sent) == 1


async def test_password_reset_token_single_use(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        email, _ = await _register(c)
        mail.sent.clear()  # drop the registration verification mail (S9b)
        await c.post("/v1/auth/password/forgot", json={"email": email})
        token = _reset_token(mail.sent[0][2])
        first = await c.post(
            "/v1/auth/password/reset", json={"token": token, "password": "passwort-eins-langgenug"}
        )
        assert first.status_code == 204
        again = await c.post(
            "/v1/auth/password/reset", json={"token": token, "password": "passwort-zwei-langgenug"}
        )
        assert again.status_code == 400
        assert again.json()["type"].endswith("reset_invalid")


async def test_password_reset_revokes_sessions(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        email, _ = await _register(c)  # active session
        assert (await c.get("/v1/auth/me")).status_code == 200
        mail.sent.clear()  # drop the registration verification mail (S9b)
        await c.post("/v1/auth/password/forgot", json={"email": email})
        token = _reset_token(mail.sent[0][2])
        await c.post(
            "/v1/auth/password/reset", json={"token": token, "password": "noch-ein-sicheres-pw"}
        )
        # the session that requested the reset is revoked too (a reset kills all sessions)
        assert (await c.get("/v1/auth/me")).status_code == 401


# ------------------------------------------------------- e-mail verification (S9b)


async def test_email_verification_flow(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        await _register(c)
        # registration sent a verification mail; /me starts unverified
        assert len(mail.sent) == 1
        assert (await c.get("/v1/auth/me")).json()["email_verified"] is False
        token = _reset_token(mail.sent[0][2])  # extracts ?token=... from the verify link
        confirm = await c.post("/v1/auth/email/verify/confirm", json={"token": token})
        assert confirm.status_code == 204
        assert (await c.get("/v1/auth/me")).json()["email_verified"] is True


async def test_email_verification_resend_and_invalid(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        await _register(c)  # 1 mail
        resend = await c.post("/v1/auth/email/verify/request", headers=_csrf(c))
        assert resend.status_code == 204
        assert len(mail.sent) == 2  # register + resend
        bad = await c.post("/v1/auth/email/verify/confirm", json={"token": "nope-nope-nope"})
        assert bad.status_code == 400
        assert bad.json()["type"].endswith("verify_invalid")


async def test_email_verification_token_single_use(app: FastAPI) -> None:
    mail = _CaptureMail()
    app.dependency_overrides[get_mail] = lambda: mail
    async with _client(app) as c:
        await _register(c)
        token = _reset_token(mail.sent[0][2])
        first = await c.post("/v1/auth/email/verify/confirm", json={"token": token})
        assert first.status_code == 204
        again = await c.post("/v1/auth/email/verify/confirm", json={"token": token})
        assert again.status_code == 400


# ------------------------------------------------------- profile (If-Match) (S11)


async def test_profile_get_and_update(app: FastAPI) -> None:
    async with _client(app) as c:
        await _register(c)
        got = await c.get("/v1/account/profile")
        assert got.status_code == 200
        etag = got.headers["etag"]
        assert got.json()["display_name"] == "Tester"
        patched = await c.patch(
            "/v1/account/profile",
            json={"display_name": "Neu", "work_hours": "Mo-Fr 9-17", "dietary": ["vegan"]},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert patched.status_code == 200
        body = patched.json()
        assert body["display_name"] == "Neu"
        assert body["work_hours"] == "Mo-Fr 9-17"
        assert body["dietary"] == ["vegan"]
        assert patched.headers["etag"] != etag  # version (ETag) bumped by the trigger
        # the change is visible on /me too
        assert (await c.get("/v1/auth/me")).json()["display_name"] == "Neu"


async def test_profile_if_match_conflict(app: FastAPI) -> None:
    async with _client(app) as c:
        await _register(c)
        etag = (await c.get("/v1/account/profile")).headers["etag"]
        ok = await c.patch(
            "/v1/account/profile",
            json={"display_name": "A"},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert ok.status_code == 200
        # the same (now stale) ETag is refused
        stale = await c.patch(
            "/v1/account/profile",
            json={"display_name": "B"},
            headers={**_csrf(c), "If-Match": etag},
        )
        assert stale.status_code == 412
        assert stale.json()["type"].endswith("precondition_failed")


async def test_profile_requires_if_match(app: FastAPI) -> None:
    async with _client(app) as c:
        await _register(c)
        resp = await c.patch("/v1/account/profile", json={"display_name": "X"}, headers=_csrf(c))
        assert resp.status_code == 428
        assert resp.json()["type"].endswith("precondition_required")


# ------------------------------------------------------- child accounts (PIN) (S12)


async def _admin_with_household(client: AsyncClient) -> str:
    await _register(client)
    resp = await client.post("/v1/households", json={"name": "Familie"}, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()["household_id"]


async def _add_child(client: AsyncClient, username: str = "kind1", pin: str = "1234") -> object:
    return await client.post(
        "/v1/household/children",
        json={"display_name": "Kind", "username": username, "pin": pin},
        headers=_csrf(client),
    )


async def test_child_create_and_login(app: FastAPI) -> None:
    async with _client(app) as admin:
        household_id = await _admin_with_household(admin)
        assert (await _add_child(admin)).status_code == 201
        # the child logs in on a fresh client with username + PIN and lands in the household
        async with _client(app) as child:
            login = await child.post(
                "/v1/auth/child-login",
                json={"household_id": household_id, "username": "kind1", "pin": "1234"},
            )
            assert login.status_code == 200
            me = (await child.get("/v1/auth/me")).json()
            assert me["role"] == "child"
            assert me["household_id"] == household_id


async def test_child_login_wrong_pin(app: FastAPI) -> None:
    async with _client(app) as admin:
        household_id = await _admin_with_household(admin)
        await _add_child(admin)
        async with _client(app) as child:
            resp = await child.post(
                "/v1/auth/child-login",
                json={"household_id": household_id, "username": "kind1", "pin": "9999"},
            )
            assert resp.status_code == 401
            assert resp.json()["type"].endswith("invalid_pin")


async def test_child_login_rate_limited(app: FastAPI) -> None:
    async with _client(app) as admin:
        household_id = await _admin_with_household(admin)
        await _add_child(admin)
        async with _client(app) as child:
            wrong = {"household_id": household_id, "username": "kind1", "pin": "0000"}
            for _ in range(5):
                assert (await child.post("/v1/auth/child-login", json=wrong)).status_code == 401
            # locked out -> 429 even with the correct PIN
            locked = await child.post(
                "/v1/auth/child-login",
                json={"household_id": household_id, "username": "kind1", "pin": "1234"},
            )
            assert locked.status_code == 429
            assert locked.json()["type"].endswith("too_many_attempts")


async def test_child_create_requires_admin(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_with_household(admin)
        code = (await admin.post("/v1/household/invites", json={}, headers=_csrf(admin))).json()[
            "code"
        ]
    async with _client(app) as member:
        await _register(member)
        assert (
            await member.post("/v1/households/join", json={"code": code}, headers=_csrf(member))
        ).status_code == 201
        # a plain member cannot create a child (admin-only)
        assert (await _add_child(member, username="x")).status_code == 403


async def test_child_username_unique_per_household(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_with_household(admin)
        assert (await _add_child(admin, username="kind")).status_code == 201
        dup = await _add_child(admin, username="kind", pin="5678")
        assert dup.status_code == 409
        assert dup.json()["type"].endswith("username_taken")
