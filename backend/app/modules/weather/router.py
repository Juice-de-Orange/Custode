"""HTTP layer for ``weather`` (KONZEPT §5.14). Reading the forecast is member/admin; setting the
household location is admin-only (CSRF on writes). Weather is optional (Graceful Enhancement): with
no location or the null provider, ``GET /v1/weather`` returns a populated-but-empty view, not an
error."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.weather import service
from app.modules.weather.models import WeatherLocation
from app.modules.weather.schemas import (
    GeocodeResult,
    LocationIn,
    LocationResponse,
    WeatherResponse,
)

weather_router = APIRouter(prefix="/v1/weather", tags=["weather"])

# Setting the household location is an admin action; reading is any member/admin.
AdminPrincipal = Annotated[Principal, Depends(require_role(Role.admin))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _location_response(location: WeatherLocation) -> LocationResponse:
    return LocationResponse(lat=location.lat, lon=location.lon, label=location.label)


@weather_router.get("")
async def get_weather(principal: CurrentPrincipal, session: ScopedSession) -> WeatherResponse:
    """The household's weather: its location (if set) and the current forecast (empty on the base
    path — no location, null provider, or upstream failure)."""
    _require_household(principal)
    location = await service.get_location(session)
    forecast = await service.get_forecast(session)
    return WeatherResponse(
        configured=location is not None,
        location=_location_response(location) if location is not None else None,
        forecast=forecast,
    )


@weather_router.get("/geocode")
async def geocode(
    principal: CurrentPrincipal,
    q: Annotated[str, Query(min_length=1, max_length=120)],
) -> list[GeocodeResult]:
    """Resolve a place name to coordinate candidates (Open-Meteo geocoding), so the user picks a
    place instead of typing raw lat/lon. Empty when weather is off / upstream down (graceful)."""
    _require_household(principal)
    return await service.search_places(q)


@weather_router.put("/location", dependencies=[Depends(require_csrf)])
async def put_location(
    payload: LocationIn, principal: AdminPrincipal, session: ScopedSession
) -> LocationResponse:
    """Set or update the household's coarse weather location (admin-only)."""
    household_id = _require_household(principal)
    location = await service.set_location(session, household_id=household_id, data=payload)
    return _location_response(location)


@weather_router.delete(
    "/location", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_location(principal: AdminPrincipal, session: ScopedSession) -> None:
    """Clear the household's weather location — weather returns to the empty base path."""
    _require_household(principal)
    await service.clear_location(session)
