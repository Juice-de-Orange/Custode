"""weather use-cases (KONZEPT §5.14). Location CRUD runs on the request's RLS-scoped session; the
forecast is fetched through the configured provider and cached in Redis (coarse coords, short TTL).
Everything degrades gracefully: no location/provider data -> an empty forecast, never a 5xx."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.redis import get_redis
from app.modules.weather import provider as weather_provider
from app.modules.weather.models import WeatherLocation
from app.modules.weather.provider import WeatherProvider, get_provider
from app.modules.weather.schemas import Forecast, GeocodeResult, LocationIn
from app.settings import get_settings


async def get_location(session: AsyncSession) -> WeatherLocation | None:
    """The household's location (RLS-scoped), or None if unset."""
    location: WeatherLocation | None = await session.scalar(
        select(WeatherLocation).where(WeatherLocation.deleted_at.is_(None))
    )
    return location


async def set_location(
    session: AsyncSession, *, household_id: uuid.UUID, data: LocationIn
) -> WeatherLocation:
    """Upsert the household's single weather location (admin-only at the router)."""
    location = await get_location(session)
    if location is None:
        location = WeatherLocation(
            household_id=household_id, lat=data.lat, lon=data.lon, label=data.label
        )
        session.add(location)
    else:
        location.lat = data.lat
        location.lon = data.lon
        location.label = data.label
    await session.flush()
    return location


async def clear_location(session: AsyncSession) -> None:
    """Soft-delete the household's location (weather returns to the base path). No-op if unset."""
    location = await get_location(session)
    if location is not None:
        location.deleted_at = datetime.now(UTC)


def _cache_key(lat: float, lon: float) -> str:
    # Coarse key (2 decimals ~1 km) so nearby households share a cached forecast and we stay within
    # Open-Meteo's fair-use limits.
    return f"weather:{lat:.2f}:{lon:.2f}"


async def get_forecast(
    session: AsyncSession, *, provider: WeatherProvider | None = None
) -> Forecast | None:
    """Forecast for the household's location, or None (base path) if no location is set, the
    provider has no data, or the upstream call failed. Cached in Redis for the configured TTL."""
    location = await get_location(session)
    if location is None:
        return None
    key = _cache_key(location.lat, location.lon)
    redis = get_redis()
    cached = await redis.get(key)
    if cached is not None:
        return Forecast.model_validate_json(cached)
    chosen = provider if provider is not None else get_provider()
    forecast = await chosen.fetch(location.lat, location.lon)
    if forecast is None:
        return None
    await redis.set(key, forecast.model_dump_json(), ex=get_settings().weather_cache_ttl_s)
    return forecast


async def search_places(query: str) -> list[GeocodeResult]:
    """Resolve a place name to coordinate candidates (Open-Meteo geocoding), cached in Redis for a
    day (names rarely move). Empty when weather is off / query blank / upstream down (graceful)."""
    normalized = query.strip().lower()
    if not normalized:
        return []
    redis = get_redis()
    key = f"weather:geocode:{normalized}"
    cached = await redis.get(key)
    if cached is not None:
        return [GeocodeResult.model_validate(r) for r in json.loads(cached)]
    results = await weather_provider.geocode(query)
    if results:
        payload = json.dumps([r.model_dump() for r in results])
        await redis.set(key, payload, ex=86400)
    return results
