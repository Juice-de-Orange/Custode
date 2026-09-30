"""Pure Open-Meteo geocoding response mapping (KONZEPT §5.14, ADR-0045) — no DB, no network, so it
is unit-testable without Docker. Maps the ``/v1/search`` JSON (a ``results`` array) into the
``GeocodeResult`` contract. Defensive: missing/garbled entries are skipped, not fatal."""

from __future__ import annotations

from typing import Any

from app.modules.weather.schemas import GeocodeResult


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def parse_geocode(payload: Any) -> list[GeocodeResult]:
    """Map an Open-Meteo geocoding body into place candidates (skips entries lacking name/coords).

    Each kept entry needs a string ``name`` and numeric ``latitude``/``longitude``."""
    if not isinstance(payload, dict):
        return []
    results = payload.get("results")
    if not isinstance(results, list):
        return []
    out: list[GeocodeResult] = []
    for entry in results:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        lat = _num(entry.get("latitude"))
        lon = _num(entry.get("longitude"))
        if not isinstance(name, str) or lat is None or lon is None:
            continue
        country = entry.get("country")
        admin1 = entry.get("admin1")
        out.append(
            GeocodeResult(
                name=name,
                lat=lat,
                lon=lon,
                country=country if isinstance(country, str) else None,
                admin1=admin1 if isinstance(admin1, str) else None,
            )
        )
    return out
