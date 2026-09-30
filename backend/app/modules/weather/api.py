"""Exported service interface for ``weather``. The Scheduling-Engine reads the household forecast
one-way through this seam (scheduling -> weather.api), never the table or provider directly."""

from app.modules.weather.service import get_forecast

__all__ = ["get_forecast"]
