"""Unit tests for Open-Meteo parsing + the null adapter (KONZEPT §5.14, ADR-0045) — pure, no DB,
no network, no Docker. Covers both Graceful-Enhancement paths: data present and data absent."""

from __future__ import annotations

import pytest

from app.modules.weather.forecast import parse_open_meteo
from app.modules.weather.geocode import parse_geocode
from app.modules.weather.provider import NullWeatherProvider

_SAMPLE = {
    "current": {"temperature_2m": 19.4, "weather_code": 3, "is_day": 1},
    "daily": {
        "time": ["2026-06-24", "2026-06-25", "2026-06-26"],
        "weather_code": [3, 61, 0],
        "temperature_2m_max": [22.1, 18.0, 25.5],
        "temperature_2m_min": [12.0, 11.2, 14.0],
        "precipitation_probability_max": [10, 80, 0],
    },
}


def test_parses_current_and_daily() -> None:
    fc = parse_open_meteo(_SAMPLE)
    assert fc.current is not None
    assert fc.current.temperature_c == 19.4
    assert fc.current.weather_code == 3
    assert fc.current.is_day is True
    assert [d.date for d in fc.daily] == ["2026-06-24", "2026-06-25", "2026-06-26"]
    assert fc.daily[1].precipitation_probability_max == 80
    assert fc.daily[1].temp_max_c == 18.0


def test_missing_current_is_tolerated() -> None:
    fc = parse_open_meteo({"daily": _SAMPLE["daily"]})
    assert fc.current is None
    assert len(fc.daily) == 3


def test_short_arrays_skip_incomplete_days() -> None:
    payload = {
        "daily": {
            "time": ["2026-06-24", "2026-06-25"],
            "weather_code": [3],  # only one code -> day 2 is incomplete and dropped
            "temperature_2m_max": [22.1, 18.0],
            "temperature_2m_min": [12.0, 11.2],
            "precipitation_probability_max": [10, 80],
        }
    }
    fc = parse_open_meteo(payload)
    assert [d.date for d in fc.daily] == ["2026-06-24"]


def test_garbage_payload_yields_empty_forecast() -> None:
    fc = parse_open_meteo("not a dict")
    assert fc.current is None
    assert fc.daily == []


async def test_null_provider_returns_none() -> None:
    assert await NullWeatherProvider().fetch(48.2, 16.37) is None


@pytest.mark.parametrize("missing_temp", [{"weather_code": 1, "is_day": 1}])
def test_current_without_temperature_is_none(missing_temp: dict[str, object]) -> None:
    fc = parse_open_meteo({"current": missing_temp, "daily": {"time": []}})
    assert fc.current is None


def test_parse_geocode_maps_results() -> None:
    payload = {
        "results": [
            {
                "name": "Wien",
                "latitude": 48.20849,
                "longitude": 16.37208,
                "country": "Österreich",
                "admin1": "Wien",
            },
            {"name": "Wien", "latitude": 1.0},  # no longitude -> skipped
            "garbage",
        ]
    }
    out = parse_geocode(payload)
    assert len(out) == 1
    assert out[0].name == "Wien"
    assert out[0].lat == 48.20849
    assert out[0].country == "Österreich"


def test_parse_geocode_handles_empty_and_garbage() -> None:
    assert parse_geocode({}) == []
    assert parse_geocode({"results": "nope"}) == []
    assert parse_geocode("not a dict") == []
