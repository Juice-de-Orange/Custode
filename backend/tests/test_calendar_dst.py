"""DST test suite for RRULE expansion (KONZEPT §5.11 Phase-5-Ziel „DST-Testsuite grün", ADR-0047) —
pure, no DB, no Docker. Proves a series anchored in a zone keeps its wall-clock time across the
spring/autumn DST switch, while a UTC-anchored series deliberately does not."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.modules.calendar.expand import expand_occurrences

_VIENNA = ZoneInfo("Europe/Vienna")


def _wall(dt: datetime) -> tuple[int, int]:
    """The (hour, minute) of a UTC instant rendered in Vienna local time."""
    local = dt.astimezone(_VIENNA)
    return local.hour, local.minute


def test_weekly_event_keeps_wall_clock_across_spring_dst() -> None:
    # "Monday 09:00 Vienna" starting 2026-03-23 (CET, UTC+1). The spring switch is 2026-03-29.
    start = datetime(2026, 3, 23, 9, 0, tzinfo=_VIENNA).astimezone(UTC)
    end = datetime(2026, 3, 23, 10, 0, tzinfo=_VIENNA).astimezone(UTC)
    occ = expand_occurrences(
        start,
        end,
        "FREQ=WEEKLY;BYDAY=MO",
        datetime(2026, 3, 23, tzinfo=UTC),
        datetime(2026, 4, 13, 23, tzinfo=UTC),
        None,
        "Europe/Vienna",
    )
    # Every Monday stays 09:00 Vienna wall-clock, even after the clocks jump forward.
    assert [s.date().isoformat() for _o, s, _e in occ] == [
        "2026-03-23",
        "2026-03-30",
        "2026-04-06",
        "2026-04-13",
    ]
    assert all(_wall(s) == (9, 0) for _o, s, _e in occ)
    # Concretely: before the switch 09:00 CET == 08:00 UTC; after, 09:00 CEST == 07:00 UTC.
    assert occ[0][1].astimezone(UTC).hour == 8
    assert occ[1][1].astimezone(UTC).hour == 7


def test_weekly_event_keeps_wall_clock_across_autumn_dst() -> None:
    # Autumn switch is 2026-10-25 (clocks fall back). "Friday 18:00 Vienna" from 2026-10-23.
    start = datetime(2026, 10, 23, 18, 0, tzinfo=_VIENNA).astimezone(UTC)
    end = datetime(2026, 10, 23, 19, 0, tzinfo=_VIENNA).astimezone(UTC)
    occ = expand_occurrences(
        start,
        end,
        "FREQ=WEEKLY;BYDAY=FR",
        datetime(2026, 10, 23, tzinfo=UTC),
        datetime(2026, 11, 7, 23, tzinfo=UTC),
        None,
        "Europe/Vienna",
    )
    assert all(_wall(s) == (18, 0) for _o, s, _e in occ)
    # Before the switch 18:00 CEST == 16:00 UTC; after, 18:00 CET == 17:00 UTC.
    assert occ[0][1].astimezone(UTC).hour == 16
    assert occ[-1][1].astimezone(UTC).hour == 17


def test_utc_anchored_series_drifts_in_local_time() -> None:
    # Same rule, but tzid="UTC": the UTC instant is fixed, so the Vienna wall-clock drifts +1h
    # after the spring switch. This is the behaviour P5-S9 fixes for zoned events.
    start = datetime(2026, 3, 23, 8, 0, tzinfo=UTC)  # 09:00 CET
    end = datetime(2026, 3, 23, 9, 0, tzinfo=UTC)
    occ = expand_occurrences(
        start,
        end,
        "FREQ=WEEKLY;BYDAY=MO",
        datetime(2026, 3, 23, tzinfo=UTC),
        datetime(2026, 4, 6, 23, tzinfo=UTC),
        None,
        "UTC",
    )
    assert _wall(occ[0][1]) == (9, 0)  # before switch: 09:00 Vienna
    assert _wall(occ[1][1]) == (10, 0)  # after switch: drifted to 10:00 Vienna


def test_daily_event_skips_no_days_around_dst() -> None:
    # A daily series across the spring gap still yields one occurrence per calendar day.
    start = datetime(2026, 3, 27, 12, 0, tzinfo=_VIENNA).astimezone(UTC)
    end = datetime(2026, 3, 27, 12, 30, tzinfo=_VIENNA).astimezone(UTC)
    occ = expand_occurrences(
        start,
        end,
        "FREQ=DAILY",
        datetime(2026, 3, 27, tzinfo=UTC),
        datetime(2026, 3, 31, 23, tzinfo=UTC),
        None,
        "Europe/Vienna",
    )
    assert [s.astimezone(_VIENNA).date().isoformat() for _o, s, _e in occ] == [
        "2026-03-27",
        "2026-03-28",
        "2026-03-29",
        "2026-03-30",
        "2026-03-31",
    ]
    assert all(_wall(s) == (12, 0) for _o, s, _e in occ)
