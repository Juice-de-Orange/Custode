from __future__ import annotations

from sqlalchemy import Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class WeatherLocation(HouseholdScoped, Base):
    """The household's coarse location for weather (KONZEPT §5.14). One row per household (upsert).
    RLS: household_id (tenant isolation). ``lat``/``lon`` are stored deliberately coarse (the UI
    rounds first); the value feeds the Open-Meteo forecast and is never precise tracking."""

    __tablename__ = "weather_locations"

    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    label: Mapped[str | None] = mapped_column(String(120))
