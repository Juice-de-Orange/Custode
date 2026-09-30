"""Weather providers (KONZEPT §5.14, ADR-0045). Two implementations behind one protocol so every
feature has a full base path without an upstream (Graceful Enhancement, CLAUDE.md):

- ``OpenMeteoProvider`` calls the public Open-Meteo API. The host is **fixed** and only numeric,
  bounds-checked lat/lon vary, so there is no SSRF surface (unlike the recipe importer's
  user-supplied URLs). Any upstream failure returns ``None`` — the caller degrades to an empty
  forecast rather than erroring.
- ``NullWeatherProvider`` always returns ``None`` (the explicit base path; selected when the
  operator sets ``weather_provider=null`` or upstream is intentionally disabled).

The provider is chosen by the operator-level ``weather_provider`` setting; tests inject a fake."""

from __future__ import annotations

from typing import Protocol

import httpx
import structlog

from app.modules.weather.forecast import CURRENT_FIELDS, DAILY_FIELDS, parse_open_meteo
from app.modules.weather.geocode import parse_geocode
from app.modules.weather.schemas import Forecast, GeocodeResult
from app.settings import get_settings

log = structlog.get_logger(__name__)

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST_DAYS = 3
_GEOCODE_COUNT = 6
_TIMEOUT = httpx.Timeout(8.0, connect=4.0)


class WeatherProvider(Protocol):
    async def fetch(self, lat: float, lon: float) -> Forecast | None:
        """Return a forecast for the coordinates, or ``None`` to signal the base path (no data)."""
        ...


class NullWeatherProvider:
    """The base path: no upstream, always empty. Keeps weather fully optional."""

    async def fetch(self, lat: float, lon: float) -> Forecast | None:
        return None


class OpenMeteoProvider:
    """Fetch + parse an Open-Meteo forecast. Fixed host, numeric params -> no SSRF."""

    async def fetch(self, lat: float, lon: float) -> Forecast | None:
        params = {
            "latitude": f"{lat:.4f}",
            "longitude": f"{lon:.4f}",
            "current": CURRENT_FIELDS,
            "daily": DAILY_FIELDS,
            "timezone": "UTC",
            "forecast_days": str(_FORECAST_DAYS),
        }
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.get(_OPEN_METEO_URL, params=params)
                resp.raise_for_status()
                return parse_open_meteo(resp.json())
        except (httpx.HTTPError, ValueError) as exc:
            # Graceful degradation: log a reference (no PII — coords are coarse) and fall back.
            log.warning("weather_fetch_failed", error_ref="WEATHER_UPSTREAM", error=str(exc))
            return None


def get_provider() -> WeatherProvider:
    """The configured provider. ``null`` (or any non-``open-meteo`` value) selects the base path."""
    if get_settings().weather_provider == "open-meteo":
        return OpenMeteoProvider()
    return NullWeatherProvider()


async def geocode(query: str) -> list[GeocodeResult]:
    """Resolve a place name to coordinate candidates via Open-Meteo's geocoding API. Fixed host,
    only the name varies (sent as a query param) -> no SSRF. Empty list when weather is disabled
    (null provider), the query is blank, or the upstream call fails (graceful base path)."""
    query = query.strip()
    if not query or get_settings().weather_provider != "open-meteo":
        return []
    params = {"name": query, "count": str(_GEOCODE_COUNT), "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_GEOCODE_URL, params=params)
            resp.raise_for_status()
            return parse_geocode(resp.json())
    except (httpx.HTTPError, ValueError) as exc:
        log.warning("weather_geocode_failed", error_ref="WEATHER_GEOCODE", error=str(exc))
        return []
