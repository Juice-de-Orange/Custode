"""End-to-end HTTP test for scheduling (Testcontainers PG 18 + Redis): slot suggestions avoid the
caller's busy calendar events (read via calendar.api). Skipped without Docker."""

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


async def _create_event(client: AsyncClient, **fields: object) -> dict[str, object]:
    resp = await client.post("/v1/calendar/events", json=fields, headers=_csrf(client))
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_slots_avoid_busy_events(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # A busy event 2026-07-01 09:00-11:00; ask for 1h slots that day, work hours 09-17.
        await _create_event(
            admin,
            title="Meeting",
            starts_at="2026-07-01T09:00:00+00:00",
            ends_at="2026-07-01T11:00:00+00:00",
            busy=True,
        )
        resp = await admin.get(
            "/v1/scheduling/slots",
            params={
                "from": "2026-07-01T00:00:00+00:00",
                "to": "2026-07-01T20:00:00+00:00",
                "duration_min": 60,
                "day_start": 9,
                "day_end": 17,
                "limit": 1,
            },
        )
        assert resp.status_code == 200, resp.text
        slots = resp.json()
        assert len(slots) == 1
        # The first free 1h slot starts at 11:00 (right after the meeting).
        assert slots[0]["start"].startswith("2026-07-01T11:00")
        assert "no_conflict" in slots[0]["reasons"]


async def test_non_busy_event_does_not_block(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # A non-busy (busy=false) event must not occupy the slot.
        await _create_event(
            admin,
            title="Tentative",
            starts_at="2026-07-02T09:00:00+00:00",
            ends_at="2026-07-02T11:00:00+00:00",
            busy=False,
        )
        resp = await admin.get(
            "/v1/scheduling/slots",
            params={
                "from": "2026-07-02T00:00:00+00:00",
                "to": "2026-07-02T20:00:00+00:00",
                "duration_min": 60,
                "day_start": 9,
                "day_end": 17,
                "limit": 1,
            },
        )
        slots = resp.json()
        assert slots[0]["start"].startswith("2026-07-02T09:00")


async def test_own_absence_blocks_slots(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        # An absence 2026-07-03 09:00-13:00 (even though absences may be busy=false) must block.
        await _create_event(
            admin,
            title="Urlaub",
            starts_at="2026-07-03T09:00:00+00:00",
            ends_at="2026-07-03T13:00:00+00:00",
            kind="absence",
            busy=False,
        )
        resp = await admin.get(
            "/v1/scheduling/slots",
            params={
                "from": "2026-07-03T00:00:00+00:00",
                "to": "2026-07-03T20:00:00+00:00",
                "duration_min": 60,
                "day_start": 9,
                "day_end": 17,
                "limit": 1,
            },
        )
        slots = resp.json()
        assert slots[0]["start"].startswith("2026-07-03T13:00")
        assert "avoids_absence" in slots[0]["reasons"]


async def test_rainy_day_tags_slots(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.weather.schemas import DailyWeather, Forecast

    class _RainProvider:
        async def fetch(self, lat: float, lon: float) -> Forecast | None:
            return Forecast(
                current=None,
                daily=[
                    DailyWeather(
                        date="2026-07-04",
                        temp_min_c=12.0,
                        temp_max_c=18.0,
                        weather_code=61,
                        precipitation_probability_max=85,
                    )
                ],
            )

    monkeypatch.setattr("app.modules.weather.service.get_provider", lambda: _RainProvider())
    async with _client(app) as admin:
        await _admin_household(admin)
        await admin.put(
            "/v1/weather/location", json={"lat": 48.2, "lon": 16.37}, headers=_csrf(admin)
        )
        resp = await admin.get(
            "/v1/scheduling/slots",
            params={
                "from": "2026-07-04T00:00:00+00:00",
                "to": "2026-07-04T20:00:00+00:00",
                "duration_min": 60,
                "day_start": 9,
                "day_end": 17,
                "limit": 1,
            },
        )
        slots = resp.json()
        assert "rain_warning" in slots[0]["reasons"]


async def test_invalid_hours_rejected(app: FastAPI) -> None:
    async with _client(app) as admin:
        await _admin_household(admin)
        resp = await admin.get(
            "/v1/scheduling/slots",
            params={"day_start": 18, "day_end": 9},
        )
        assert resp.status_code == 422
