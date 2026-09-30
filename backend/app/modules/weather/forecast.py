"""Pure Open-Meteo response mapping (KONZEPT §5.14, ADR-0045) — no DB, no network, so it is
unit-testable without Docker (mirror of the calendar pure-function pattern). Maps the Open-Meteo
``/v1/forecast`` JSON (``current`` + parallel ``daily`` arrays) into the ``Forecast`` contract.
Defensive: missing/short arrays yield fewer days rather than raising — a degraded forecast still
beats a 500."""

from __future__ import annotations

from typing import Any

from app.modules.weather.schemas import CurrentWeather, DailyWeather, Forecast

# The exact Open-Meteo query this parser expects (kept next to the parser so they stay in sync).
CURRENT_FIELDS = "temperature_2m,weather_code,is_day"
DAILY_FIELDS = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _parse_current(raw: Any) -> CurrentWeather | None:
    if not isinstance(raw, dict):
        return None
    temp = _num(raw.get("temperature_2m"))
    code = raw.get("weather_code")
    if temp is None or not isinstance(code, int):
        return None
    return CurrentWeather(temperature_c=temp, weather_code=code, is_day=bool(raw.get("is_day")))


def _parse_daily(raw: Any) -> list[DailyWeather]:
    if not isinstance(raw, dict):
        return []
    dates = raw.get("time")
    if not isinstance(dates, list):
        return []
    codes = raw.get("weather_code") or []
    highs = raw.get("temperature_2m_max") or []
    lows = raw.get("temperature_2m_min") or []
    probs = raw.get("precipitation_probability_max") or []

    def _at(seq: Any, i: int) -> Any:
        return seq[i] if isinstance(seq, list) and i < len(seq) else None

    out: list[DailyWeather] = []
    for i, date in enumerate(dates):
        if not isinstance(date, str):
            continue
        high = _num(_at(highs, i))
        low = _num(_at(lows, i))
        code = _at(codes, i)
        if high is None or low is None or not isinstance(code, int):
            continue
        prob = _at(probs, i)
        out.append(
            DailyWeather(
                date=date,
                temp_min_c=low,
                temp_max_c=high,
                weather_code=code,
                precipitation_probability_max=prob if isinstance(prob, int) else None,
            )
        )
    return out


def parse_open_meteo(payload: Any) -> Forecast:
    """Map an Open-Meteo ``/v1/forecast`` JSON body into a ``Forecast`` (lenient on gaps)."""
    if not isinstance(payload, dict):
        return Forecast(current=None, daily=[])
    return Forecast(
        current=_parse_current(payload.get("current")),
        daily=_parse_daily(payload.get("daily")),
    )
