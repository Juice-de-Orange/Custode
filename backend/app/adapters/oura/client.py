"""Oura data adapter (P9-S6) — reads one member's daily values via the v2 API.

Three endpoints under ``api.ouraring.com/v2/usercollection`` cover everything KONZEPT §5.15
names: ``daily_sleep`` (score), ``sleep`` (duration), ``daily_readiness`` (score + resting heart
rate) and ``daily_activity`` (steps, active calories). Each is queried for a single day, so a
partial outage costs one signal, not the whole record.

**Never raises for missing data.** An empty or partial answer is a legitimate result — the user
may not have worn the ring — and every dependent feature has a base path (Graceful Enhancement).
The one exception is an authentication failure (401/403): that is a state the caller must react
to (flag the connection ``needs_reauth``), so it raises ``WearableAuthError("token_rejected")``.

Fixed host, no user-supplied URL → not the SSRF surface ``kernel/fetch`` guards, same as the
Open-Meteo/GitHub adapters. No retry layer (the repo has none); the next nightly tick retries.

**Field mapping is unverified against the live API** — it was written from the documented v2
shape, and nobody has run it against a real Oura account yet. ``_combine`` is deliberately
defensive (every field independently optional, out-of-range values dropped rather than clamped),
so a wrong guess costs a missing value, never a bad one. The first real connection is a manual
test step (`docs/MANUAL_TESTS.md`, Abschnitt E) — correct the mapping there, not by guessing here.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.kernel.ports.wearable import UNKNOWN_WEARABLE, WearableAuthError, WearableDaily
from app.logging import get_logger
from app.settings import Settings

_log = get_logger("adapters.oura")

API_BASE = "https://api.ouraring.com/v2/usercollection"


class OuraClient:
    def __init__(self, settings: Settings) -> None:
        self._timeout = settings.oura_timeout_s

    async def fetch_daily(self, *, access_token: str, day: date) -> WearableDaily:
        params = {"start_date": day.isoformat(), "end_date": day.isoformat()}
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                sleep_daily = await self._get(client, "daily_sleep", params, headers)
                sleep_detail = await self._get(client, "sleep", params, headers)
                readiness = await self._get(client, "daily_readiness", params, headers)
                activity = await self._get(client, "daily_activity", params, headers)
        except WearableAuthError:
            raise
        except httpx.HTTPError as exc:
            # Failure class only — a body may echo the token back. Not an error for the caller:
            # a missed night is a missing value, not a broken connection.
            _log.warning("oura_fetch_failed", error=type(exc).__name__)
            return UNKNOWN_WEARABLE
        return _combine(sleep_daily, sleep_detail, readiness, activity)

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        params: dict[str, str],
        headers: dict[str, str],
    ) -> list[dict[str, Any]]:
        resp = await client.get(f"{API_BASE}/{path}", params=params, headers=headers)
        if resp.status_code in (401, 403):
            # The token is the problem — the caller flags the connection for re-authorisation.
            raise WearableAuthError("token_rejected")
        if resp.status_code == 404:
            return []  # endpoint not covered by the granted scopes
        resp.raise_for_status()
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _first(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def _int_in(value: object, *, low: int, high: int) -> int | None:
    """Accept a number only inside the DB CHECK range.

    The migration constrains scores to 0-100, resting heart rate to 20-250 and counters to >= 0.
    Clamping silently would invent data; letting an out-of-range value through would abort the
    whole run on a constraint violation. Dropping the single field is the honest middle."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = int(value)
    return number if low <= number <= high else None


def _combine(
    sleep_daily: list[dict[str, Any]],
    sleep_detail: list[dict[str, Any]],
    readiness: list[dict[str, Any]],
    activity: list[dict[str, Any]],
) -> WearableDaily:
    """Map four provider payloads onto our flat shape. Unknown fields are ignored (forward
    compatibility, ARCHITECTURE §8.2); every field is independently optional."""
    sleep_row, readiness_row, activity_row = (
        _first(sleep_daily),
        _first(readiness),
        _first(activity),
    )
    # ``sleep`` returns one row per sleep period; the night's duration is their sum.
    total_sleep_s = sum(
        int(row["total_sleep_duration"])
        for row in sleep_detail
        if isinstance(row.get("total_sleep_duration"), int | float)
        and not isinstance(row.get("total_sleep_duration"), bool)
    )
    # Resting heart rate comes from the SLEEP document's ``lowest_heart_rate`` (bpm), not from
    # ``daily_readiness.contributors.resting_heart_rate`` — the latter is a 0-100 SCORE
    # contributor, and storing it as bpm would put plausible-looking nonsense in a health record.
    # The lowest rate during sleep is the standard proxy for resting heart rate.
    rhr_candidates = [
        row["lowest_heart_rate"]
        for row in sleep_detail
        if isinstance(row.get("lowest_heart_rate"), int | float)
        and not isinstance(row.get("lowest_heart_rate"), bool)
    ]
    daily = WearableDaily(
        available=True,
        sleep_score=_int_in(sleep_row.get("score"), low=0, high=100),
        sleep_minutes=(total_sleep_s // 60) if total_sleep_s > 0 else None,
        readiness=_int_in(readiness_row.get("score"), low=0, high=100),
        steps=_int_in(activity_row.get("steps"), low=0, high=10**7),
        active_kcal=_int_in(activity_row.get("active_calories"), low=0, high=10**5),
        rhr=_int_in(min(rhr_candidates) if rhr_candidates else None, low=20, high=250),
    )
    # "Reached the provider but it knew nothing" is indistinguishable from "no connection" for
    # every consumer — report it as unavailable so nothing stores an empty row.
    if not any(
        v is not None
        for v in (
            daily.sleep_score,
            daily.sleep_minutes,
            daily.readiness,
            daily.steps,
            daily.active_kcal,
            daily.rhr,
        )
    ):
        return UNKNOWN_WEARABLE
    return daily
