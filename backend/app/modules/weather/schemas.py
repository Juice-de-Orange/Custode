"""HTTP + cache contracts for ``weather`` (single source for the OpenAPI schema -> web zod client).
``Forecast`` doubles as the Redis cache shape (it serialises to JSON cleanly)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LocationIn(BaseModel):
    """Set the household's coarse weather location. Bounds are validated; the UI rounds first."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    label: str | None = Field(default=None, max_length=120)


class LocationResponse(BaseModel):
    lat: float
    lon: float
    label: str | None


class GeocodeResult(BaseModel):
    """One place candidate from a name search (Open-Meteo geocoding). The web picks one to set the
    household location, so the user never types raw coordinates."""

    name: str
    lat: float
    lon: float
    country: str | None
    admin1: str | None  # region/state, disambiguates same-named places


class CurrentWeather(BaseModel):
    temperature_c: float
    weather_code: int  # WMO weather code (0 clear .. 95+ thunderstorm)
    is_day: bool


class DailyWeather(BaseModel):
    date: str  # ISO date, YYYY-MM-DD
    temp_min_c: float
    temp_max_c: float
    weather_code: int
    precipitation_probability_max: int | None


class Forecast(BaseModel):
    """A parsed forecast. ``current`` may be absent if the provider omits it; ``daily`` is the
    per-day outlook. Also the Redis cache payload."""

    current: CurrentWeather | None
    daily: list[DailyWeather]


class WeatherResponse(BaseModel):
    """The household weather view. ``configured`` is false when no location is set; ``forecast`` is
    null when no location is set, the provider is the null adapter, or the upstream call failed —
    every one a graceful base path, not an error."""

    configured: bool
    location: LocationResponse | None
    forecast: Forecast | None
