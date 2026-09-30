from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class Forecast(BaseModel):
    available: bool = False
    temp_c: float | None = None
    precipitation_prob: float | None = None
    condition: str | None = None


UNKNOWN_FORECAST = Forecast(available=False)


class WeatherPort(Protocol):
    async def forecast(self, *, lat: float, lon: float, day: str) -> Forecast: ...
