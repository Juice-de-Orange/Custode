"""Pure unit tests for the Oura data adapter and the consent projection (P9-S6).

No Docker, no DB. The adapter tests use ``httpx.MockTransport`` so the real code path runs,
wire shape included, without a network.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import httpx
import pytest

from app.adapters.null import NullWearable
from app.adapters.oura.client import API_BASE, OuraClient, _combine
from app.kernel.ports.wearable import WearableAuthError, WearableDaily
from app.modules.wearables.sync import allowed_fields, consented_values
from app.settings import Settings

DAY = date(2026, 7, 20)

_REAL_ASYNC_CLIENT = httpx.AsyncClient  # captured before monkeypatching (avoid self-recursion)


def _client(monkeypatch: pytest.MonkeyPatch, routes: dict[str, Any]) -> OuraClient:
    """Adapter whose four endpoint calls are answered from ``routes`` (path -> data list or
    a ready ``httpx.Response``). Missing paths answer an empty collection."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.rsplit("/", 1)[-1]
        route = routes.get(path, [])
        if isinstance(route, httpx.Response):
            return route
        return httpx.Response(200, json={"data": route})

    monkeypatch.setattr(
        "app.adapters.oura.client.httpx.AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)),
    )
    return OuraClient(Settings(_env_file=None))


# ------------------------------------------------------------------ happy path


async def test_fetch_combines_all_four_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    daily = await _client(
        monkeypatch,
        {
            "daily_sleep": [{"score": 82}],
            "sleep": [{"total_sleep_duration": 27000, "lowest_heart_rate": 52}],
            "daily_readiness": [{"score": 74}],
            "daily_activity": [{"steps": 8300, "active_calories": 410}],
        },
    ).fetch_daily(access_token="at", day=DAY)

    assert daily.available is True
    assert daily.sleep_score == 82
    assert daily.sleep_minutes == 450  # 27000 s / 60
    assert daily.readiness == 74
    assert daily.steps == 8300
    assert daily.active_kcal == 410
    assert daily.rhr == 52


async def test_request_carries_the_bearer_token_and_the_single_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    monkeypatch.setattr(
        "app.adapters.oura.client.httpx.AsyncClient",
        lambda *a, **k: _REAL_ASYNC_CLIENT(transport=httpx.MockTransport(handler)),
    )
    await OuraClient(Settings(_env_file=None)).fetch_daily(access_token="tok-123", day=DAY)

    assert len(seen) == 4  # daily_sleep, sleep, daily_readiness, daily_activity
    for request in seen:
        assert request.headers["Authorization"] == "Bearer tok-123"
        assert request.url.params["start_date"] == "2026-07-20"
        assert request.url.params["end_date"] == "2026-07-20"
        assert str(request.url).startswith(API_BASE)


def test_sleep_duration_sums_multiple_periods() -> None:
    """``sleep`` returns one row per sleep period — a nap plus a night is one night's total."""
    daily = _combine([], [{"total_sleep_duration": 18000}, {"total_sleep_duration": 5400}], [], [])
    assert daily.sleep_minutes == 390  # (18000 + 5400) / 60


def test_resting_heart_rate_is_the_lowest_measured_not_a_score() -> None:
    """Guards a mistake that is easy to make and hard to notice: Oura's
    ``daily_readiness.contributors.resting_heart_rate`` is a 0-100 SCORE. Storing it as bpm
    would put plausible-looking nonsense into a health record."""
    daily = _combine(
        [],
        [{"lowest_heart_rate": 58}, {"lowest_heart_rate": 51}],
        [{"score": 70, "contributors": {"resting_heart_rate": 95}}],
        [],
    )
    assert daily.rhr == 51  # the lowest measured rate, NOT the 95-point contributor
    assert daily.readiness == 70


# ------------------------------------------------------------------ defensive mapping


def test_missing_endpoints_yield_partial_data() -> None:
    daily = _combine([{"score": 80}], [], [], [])
    assert daily.available is True
    assert daily.sleep_score == 80
    assert (daily.readiness, daily.steps, daily.active_kcal, daily.rhr) == (None, None, None, None)


def test_completely_empty_answer_is_unavailable() -> None:
    """ "Reached the provider, it knew nothing" must not store an empty row."""
    assert _combine([], [], [], []).available is False


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"score": 140}, "sleep_score"),  # above the CHECK range
        ({"score": -3}, "sleep_score"),
        ({"score": "gut"}, "sleep_score"),
        ({"score": True}, "sleep_score"),  # bool is not a measurement
        ({"score": None}, "sleep_score"),
    ],
)
def test_out_of_range_and_wrong_typed_values_are_dropped_not_clamped(
    payload: dict[str, Any], field: str
) -> None:
    """Clamping would invent data; letting it through would abort the whole run on the DB CHECK.
    Dropping the single field is the honest middle."""
    assert getattr(_combine([payload], [], [], []), field) is None


def test_unknown_fields_are_ignored() -> None:
    daily = _combine([{"score": 80, "brand_new_metric": 1}], [], [], [])
    assert daily.sleep_score == 80


def test_rhr_outside_the_plausible_range_is_dropped() -> None:
    assert _combine([], [{"lowest_heart_rate": 3}], [], []).rhr is None


# ------------------------------------------------------------------ error handling


@pytest.mark.parametrize("status", [401, 403])
async def test_rejected_token_raises_so_the_caller_can_flag_reauth(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    client = _client(monkeypatch, {"daily_sleep": httpx.Response(status, json={})})
    with pytest.raises(WearableAuthError) as exc:
        await client.fetch_daily(access_token="at", day=DAY)
    assert exc.value.category == "token_rejected"


async def test_missing_scope_404_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An endpoint outside the granted scopes simply contributes nothing."""
    client = _client(
        monkeypatch,
        {"daily_sleep": [{"score": 80}], "daily_activity": httpx.Response(404, json={})},
    )
    daily = await client.fetch_daily(access_token="at", day=DAY)
    assert daily.sleep_score == 80
    assert daily.steps is None


async def test_server_error_degrades_to_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missed night is a missing value, not a broken connection — the run must not raise."""
    client = _client(monkeypatch, {"daily_sleep": httpx.Response(503, json={})})
    assert (await client.fetch_daily(access_token="at", day=DAY)).available is False


async def test_null_adapter_returns_a_blank_instead_of_raising() -> None:
    """Unlike NullWearableOAuth: on the DATA path a blank IS the correct neutral answer."""
    assert (await NullWearable().fetch_daily(access_token="at", day=DAY)).available is False


# ------------------------------------------------------------------ consent projection


ALL_ON = {
    "wearable_sleep": True,
    "wearable_readiness": True,
    "wearable_activity": True,
    "wearable_heartrate": True,
}
FULL = WearableDaily(
    available=True,
    sleep_score=80,
    sleep_minutes=420,
    readiness=70,
    steps=9000,
    active_kcal=400,
    rhr=55,
)


def test_full_consent_keeps_every_value() -> None:
    values = consented_values(FULL, allowed_fields(ALL_ON))
    assert values == {
        "sleep_score": 80,
        "sleep_minutes": 420,
        "readiness": 70,
        "steps": 9000,
        "active_kcal": 400,
        "rhr": 55,
    }


def test_only_consented_types_survive() -> None:
    """The provider scope is coarser than our vocabulary (`daily` covers three types) — THIS
    filter is what actually enforces per-type consent."""
    allowed = allowed_fields({**ALL_ON, "wearable_activity": False, "wearable_heartrate": False})
    values = consented_values(FULL, allowed)
    assert values["sleep_score"] == 80
    assert values["readiness"] == 70
    assert values["steps"] is None
    assert values["active_kcal"] is None
    assert values["rhr"] is None


def test_withdrawn_types_are_nulled_not_omitted() -> None:
    """A type withdrawn between two runs must LOSE its old value. An upsert that only touched
    the allowed fields would leave last night's data lying around."""
    values = consented_values(FULL, allowed_fields({"wearable_sleep": True}))
    assert set(values) == {
        "sleep_score",
        "sleep_minutes",
        "readiness",
        "steps",
        "active_kcal",
        "rhr",
    }
    assert values["readiness"] is None


def test_no_consent_means_no_fields() -> None:
    assert allowed_fields({}) == set()
    assert all(v is None for v in consented_values(FULL, set()).values())
