"""End-to-end HTTP tests for weather (Testcontainers PG 18 + Redis): location CRUD (admin-only) and
the forecast view through an injected provider — both Graceful-Enhancement paths (data + empty), no
real network. Skipped without Docker."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.kernel.db.engine as engine_mod
from app.main import create_app
from app.modules.weather.schemas import CurrentWeather, DailyWeather, Forecast
from app.settings import get_settings
from conftest import PgDatabase

_PASSWORD = "ein-sehr-sicheres-passwort"  # test fixture, not a real secret
_CSRF = "custode_csrf"


class _FakeProvider:
    """Returns a fixed forecast without touching the network (the happy path)."""

    async def fetch(self, lat: float, lon: float) -> Forecast | None:
        return Forecast(
            current=CurrentWeather(temperature_c=21.0, weather_code=1, is_day=True),
            daily=[
                DailyWeather(
                    date="2026-06-24",
                    temp_min_c=12.0,
                    temp_max_c=24.0,
                    weather_code=1,
                    precipitation_probability_max=10,
                )
            ],
        )


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


async def test_weather_empty_without_location(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.get("/v1/weather")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["configured"] is False
        assert body["location"] is None
        assert body["forecast"] is None


async def test_set_location_and_get_forecast(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.modules.weather.service.get_provider", lambda: _FakeProvider())
    async with _client(app) as admin:
        await _admin_household(admin)
        put = await admin.put(
            "/v1/weather/location",
            json={"lat": 48.2, "lon": 16.37, "label": "Wien"},
            headers=_csrf(admin),
        )
        assert put.status_code == 200, put.text
        assert put.json()["label"] == "Wien"

        got = await admin.get("/v1/weather")
        body = got.json()
        assert body["configured"] is True
        assert body["location"]["lat"] == 48.2
        assert body["forecast"]["current"]["temperature_c"] == 21.0
        assert body["forecast"]["daily"][0]["precipitation_probability_max"] == 10

        # A second call is served from the Redis cache and stays consistent.
        again = (await admin.get("/v1/weather")).json()
        assert again["forecast"]["current"]["temperature_c"] == 21.0


async def test_null_provider_degrades_to_empty_forecast(
    app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.weather.provider import NullWeatherProvider

    monkeypatch.setattr("app.modules.weather.service.get_provider", lambda: NullWeatherProvider())
    async with _client(app) as admin:
        await _admin_household(admin)
        await admin.put(
            "/v1/weather/location",
            json={"lat": 10.0, "lon": 10.0},
            headers=_csrf(admin),
        )
        body = (await admin.get("/v1/weather")).json()
        # Location is configured, but the base-path provider yields no forecast (not an error).
        assert body["configured"] is True
        assert body["forecast"] is None


async def test_member_cannot_set_location(app: FastAPI) -> None:
    async with _client(app) as admin, _client(app) as member:
        await _admin_household(admin)
        await _join_member(admin, member)
        resp = await member.put(
            "/v1/weather/location",
            json={"lat": 1.0, "lon": 2.0},
            headers=_csrf(member),
        )
        assert resp.status_code == 403


async def test_delete_location_clears_it(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        await admin.put("/v1/weather/location", json={"lat": 5.0, "lon": 5.0}, headers=_csrf(admin))
        assert (await admin.delete("/v1/weather/location", headers=_csrf(admin))).status_code == 204
        assert (await admin.get("/v1/weather")).json()["configured"] is False


async def test_geocode_returns_candidates(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.weather.schemas import GeocodeResult

    async def _fake_geocode(query: str) -> list[GeocodeResult]:
        assert query == "Wien"
        return [
            GeocodeResult(name="Wien", lat=48.2, lon=16.37, country="Österreich", admin1="Wien")
        ]

    monkeypatch.setattr("app.modules.weather.service.weather_provider.geocode", _fake_geocode)
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.get("/v1/weather/geocode", params={"q": "Wien"})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body[0]["name"] == "Wien"
        assert body[0]["lat"] == 48.2


async def test_geocode_requires_query(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        assert (await admin.get("/v1/weather/geocode")).status_code == 422


async def test_invalid_coordinates_rejected(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.put(
            "/v1/weather/location", json={"lat": 100.0, "lon": 0.0}, headers=_csrf(admin)
        )
        assert resp.status_code == 422
