"""Public demo mode (``CUSTODE_DEMO_MODE=on``, ``app/demo.py``, docs/demo.md).

The demo is reachable by anyone, with a shared login printed on the sign-in page. These tests pin
the three promises it makes:

* every path that creates accounts, sends mail, stores files, talks to the outside or would lock
  the shared account answers ``403 demo_disabled`` — server-side, before routing;
* nobody can flood it (per-IP rate limit, body cap) and search engines are told to stay away;
* with the flag off, nothing of this exists — no middleware, no route, no header.

Runs without Docker except for the rate-limit tests (Redis container, ``redis_db``).
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.adapters.null import NullMail
from app.demo import BLOCKED, RESETTING_KEY, is_blocked
from app.mail_factory import build_mail
from app.main import create_app
from app.settings import Settings

# (method, path) a visitor could try. Each must be refused.
REFUSED: tuple[tuple[str, str], ...] = (
    ("POST", "/v1/auth/register"),
    ("POST", "/v1/auth/password/forgot"),
    ("POST", "/v1/auth/password/reset"),
    ("POST", "/v1/auth/email/verify/request"),
    ("POST", "/v1/auth/email/verify/confirm"),
    ("POST", "/v1/auth/totp/setup"),
    ("POST", "/v1/auth/totp/enable"),
    ("POST", "/v1/auth/totp/disable"),
    ("POST", "/v1/auth/totp/recovery-codes"),
    ("POST", "/v1/auth/passkeys/register/begin"),
    ("POST", "/v1/auth/passkeys/register/complete"),
    ("DELETE", "/v1/auth/passkeys/0190c0de-0000-7000-8000-000000000001"),
    ("DELETE", "/v1/auth/account"),
    ("DELETE", "/v1/auth/sessions/0190c0de-0000-7000-8000-000000000001"),
    ("PATCH", "/v1/account/profile"),
    ("POST", "/v1/households"),
    ("POST", "/v1/households/join"),
    ("POST", "/v1/household/invites"),
    ("POST", "/v1/household/children"),
    ("PATCH", "/v1/household/members/0190c0de-0000-7000-8000-000000000001"),
    ("DELETE", "/v1/household/members/0190c0de-0000-7000-8000-000000000001"),
    ("POST", "/v1/household/leave"),
    ("POST", "/v1/household/dissolve"),
    ("PATCH", "/v1/household/digest"),
    ("POST", "/v1/recipes/import"),
    ("PUT", "/v1/recipes/0190c0de-0000-7000-8000-000000000001/photo"),
    ("POST", "/v1/guides/0190c0de-0000-7000-8000-000000000001/attachments"),
    ("POST", "/v1/calendar/import"),
    ("POST", "/v1/calendar/feed"),
    ("DELETE", "/v1/calendar/feed"),
    ("GET", "/v1/calendar/feed/some-secret-token.ics"),
    ("POST", "/v1/calendar/subscriptions"),
    ("PATCH", "/v1/calendar/subscriptions/0190c0de-0000-7000-8000-000000000001"),
    ("POST", "/v1/calendar/subscriptions/0190c0de-0000-7000-8000-000000000001/check"),
    ("GET", "/v1/vault/keys"),
    ("PUT", "/v1/vault/keys"),
    ("POST", "/v1/vault/items"),
    ("POST", "/v1/wearables/oura/authorize"),
    ("GET", "/v1/wearables/oura/callback"),
    ("GET", "/v1/weather/geocode"),
    ("PUT", "/v1/weather/location"),
    ("POST", "/v1/feedback"),
    ("GET", "/v1/stream"),
    ("POST", "/ops/auth/login"),
    ("GET", "/ops/me"),
)

# The demo is for clicking through the household — these must stay open.
ALLOWED: tuple[tuple[str, str], ...] = (
    ("POST", "/v1/auth/login"),
    ("POST", "/v1/auth/refresh"),
    ("POST", "/v1/auth/logout"),
    ("POST", "/v1/auth/passkeys/login/begin"),
    ("GET", "/v1/auth/me"),
    ("GET", "/v1/households"),
    ("POST", "/v1/households/0190c0de-0000-7000-8000-000000000001/switch"),
    ("GET", "/v1/household/members"),
    ("POST", "/v1/notes"),
    ("POST", "/v1/sync/shopping/batch"),
    ("PUT", "/v1/mealplan/slot"),
    ("POST", "/v1/tasks/instances/0190c0de-0000-7000-8000-000000000001/complete"),
    ("POST", "/v1/calendar/events"),
    ("GET", "/v1/calendar/subscriptions"),
    ("GET", "/v1/recipes/0190c0de-0000-7000-8000-000000000001/photo"),
    ("GET", "/v1/weather"),
    ("GET", "/v1/wearables/connections"),
    ("POST", "/v1/capture"),
    ("GET", "/v1/me/export"),
    ("GET", "/healthz"),
)

# Routes that are not in the OpenAPI schema but exist (include_in_schema=False).
_HIDDEN_ROUTES = (
    ("GET", "/v1/stream"),
    ("GET", "/v1/calendar/feed/{token}.ics"),
    ("GET", "/v1/wearables/oura/callback"),
)


def _demo_settings(**overrides: object) -> Settings:
    return Settings(demo_mode=True, **overrides)  # type: ignore[arg-type]


@pytest.fixture
async def demo_api() -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app(_demo_settings())
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def plain_api() -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app(Settings(demo_mode=False))
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# --- the list itself ------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), REFUSED)
def test_listed_paths_are_blocked(method: str, path: str) -> None:
    assert is_blocked(method, path)


@pytest.mark.parametrize(("method", "path"), ALLOWED)
def test_the_household_stays_usable(method: str, path: str) -> None:
    assert not is_blocked(method, path)


def test_every_block_rule_names_a_real_route() -> None:
    """A typo in a pattern would block nothing and look like coverage. Each rule must match at
    least one route the app actually has."""
    spec = create_app(Settings()).openapi()
    routes = [(m.upper(), p) for p, ops in spec["paths"].items() for m in ops]
    routes += list(_HIDDEN_ROUTES)
    concrete = [(m, re.sub(r"\{[^}]+\}", "x1", p)) for m, p in routes]
    for methods, pattern, why in BLOCKED:
        rx = re.compile(pattern)
        assert any(m in methods and rx.fullmatch(p) for m, p in concrete), (pattern, why)


# --- over HTTP ------------------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), REFUSED)
async def test_refused_over_http_with_demo_disabled(
    demo_api: AsyncClient, method: str, path: str
) -> None:
    response = await demo_api.request(method, path, json={})
    assert response.status_code == 403
    body = response.json()
    assert body["type"].endswith("#demo_disabled")
    assert body["reference"]  # like every problem response
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


async def test_a_large_body_is_refused_before_the_handler(demo_api: AsyncClient) -> None:
    response = await demo_api.post(
        "/v1/notes", content=b"x" * (256 * 1024 + 1), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413
    assert response.json()["type"].endswith("#demo_payload_too_large")


async def test_health_stays_reachable_and_is_noindex(demo_api: AsyncClient) -> None:
    response = await demo_api.get("/healthz")
    assert response.status_code == 200
    assert response.headers["X-Robots-Tag"] == "noindex, nofollow"


async def test_flag_off_changes_nothing(plain_api: AsyncClient) -> None:
    # Sign-up reaches its handler (validation error for the empty body), not the demo wall.
    response = await plain_api.post("/v1/auth/register", json={})
    assert response.status_code == 422
    assert "X-Robots-Tag" not in response.headers
    # The web asks /v1/demo on every page load; a normal instance answers "no demo" with a 200,
    # not a 404 that lands in every visitor's console — and without the demo's login.
    off = await plain_api.get("/v1/demo")
    assert off.status_code == 200
    assert off.json() == {"enabled": False}
    # A big body is the handler's business when the demo is off (here: 401, not 413).
    big = await plain_api.post(
        "/v1/notes", content=b"x" * (256 * 1024 + 1), headers={"content-type": "application/json"}
    )
    assert big.status_code != 413


# --- settings: the second wall ----------------------------------------------------------------


def test_demo_mode_switches_every_external_adapter_off() -> None:
    settings = _demo_settings(
        smtp_host="smtp.example.com",
        caldav_sync_enabled=True,
        oura_enabled=True,
        oura_client_id="id",
        oura_client_secret="secret",
        ollama_enabled=True,
        github_token="t",
        github_repo="o/r",
        weather_provider="open-meteo",
        storage_dir="/data/storage",
    )
    assert settings.smtp_host == ""
    assert isinstance(build_mail(settings), NullMail)
    assert not settings.caldav_sync_enabled
    assert not settings.oura_enabled
    assert not settings.ollama_enabled
    assert settings.github_token is None and settings.github_repo is None
    assert settings.weather_provider == "null"
    assert settings.storage_dir is None


def test_without_demo_mode_the_settings_are_untouched() -> None:
    settings = Settings(smtp_host="smtp.example.com", storage_dir="/data/storage")
    assert settings.demo_mode is False
    assert settings.smtp_host == "smtp.example.com"
    assert settings.storage_dir == "/data/storage"
    assert settings.weather_provider == "open-meteo"


@pytest.mark.parametrize("raw", ["on", "true", "1"])
def test_the_flag_reads_on(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("CUSTODE_DEMO_MODE", raw)
    assert Settings().demo_mode is True


# --- with Redis: rate limit and /v1/demo ------------------------------------------------------


async def test_rate_limit_per_visitor(redis_db: None) -> None:
    app = create_app(_demo_settings(demo_rate_limit=5, demo_rate_window_s=60))
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        visitor_a = {"CF-Connecting-IP": "198.51.100.7"}
        codes = [(await client.get("/v1/auth/me", headers=visitor_a)).status_code for _ in range(6)]
        assert codes[:5] == [401] * 5
        assert codes[5] == 429
        limited = await client.get("/v1/auth/me", headers=visitor_a)
        assert limited.json()["type"].endswith("#demo_rate_limited")
        assert 0 < int(limited.headers["Retry-After"]) <= 60
        # Another visitor has its own budget; probes are never limited.
        other = await client.get("/v1/auth/me", headers={"CF-Connecting-IP": "198.51.100.8"})
        assert other.status_code == 401
        assert (await client.get("/healthz", headers=visitor_a)).status_code == 200


async def test_demo_info_shows_the_login_and_the_reset_state(redis_db: None) -> None:
    from app.kernel.redis import get_redis
    from app.scripts.seed_demo import DEMO_EMAIL, DEMO_PASSWORD

    app = create_app(_demo_settings())
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        info = (await client.get("/v1/demo")).json()
        assert info["enabled"] is True
        assert (info["email"], info["password"]) == (DEMO_EMAIL, DEMO_PASSWORD)
        assert info["resetting"] is False
        await get_redis().set(RESETTING_KEY, "1")
        assert (await client.get("/v1/demo")).json()["resetting"] is True
