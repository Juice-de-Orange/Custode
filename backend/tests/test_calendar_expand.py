"""Unit tests for RRULE occurrence expansion (KONZEPT §5.11, ADR-0041) — pure, no DB, no Docker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.modules.calendar.expand import (
    expand_occurrences,
    is_occurrence,
    is_valid_rrule,
)


def _dt(day: int, hour: int = 9) -> datetime:
    return datetime(2026, 7, day, hour, 0, tzinfo=UTC)


def test_non_recurring_in_window_yields_one() -> None:
    occ = expand_occurrences(_dt(1), _dt(1, 10), None, _dt(1), _dt(31))
    assert occ == [(_dt(1), _dt(1), _dt(1, 10))]


def test_non_recurring_outside_window_yields_none() -> None:
    assert expand_occurrences(_dt(1), _dt(1, 10), None, _dt(10), _dt(31)) == []


def test_weekly_rule_expands_within_window() -> None:
    # Wed 2026-07-01 weekly -> 07-01, 07-08, 07-15, 07-22, 07-29 within July.
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=WEEKLY", _dt(1), _dt(31, 23))
    starts = [s.day for _o, s, _e in occ]
    assert starts == [1, 8, 15, 22, 29]
    # Duration is preserved on every occurrence.
    assert all(e - s == timedelta(hours=1) for _o, s, e in occ)


def test_count_caps_the_series() -> None:
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=DAILY;COUNT=3", _dt(1), _dt(31))
    assert [s.day for _o, s, _e in occ] == [1, 2, 3]


def test_until_bounds_the_series() -> None:
    occ = expand_occurrences(
        _dt(1), _dt(1, 10), "FREQ=DAILY;UNTIL=20260704T090000Z", _dt(1), _dt(31)
    )
    assert [s.day for _o, s, _e in occ] == [1, 2, 3, 4]


def test_window_clips_recurring_occurrences() -> None:
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=DAILY", _dt(10), _dt(12, 23))
    assert [s.day for _o, s, _e in occ] == [10, 11, 12]


def test_byday_selects_weekdays() -> None:
    # Mondays in July 2026: 06, 13, 20, 27 (anchored at the 01, dateutil rolls to the rule days).
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=WEEKLY;BYDAY=MO", _dt(1), _dt(31, 23))
    assert [s.day for _o, s, _e in occ] == [6, 13, 20, 27]


def test_is_valid_rrule() -> None:
    assert is_valid_rrule("FREQ=WEEKLY;BYDAY=MO,WE", dtstart=_dt(1))
    assert not is_valid_rrule("NOT-A-RULE", dtstart=_dt(1))
    assert not is_valid_rrule("FREQ=NONSENSE", dtstart=_dt(1))


def test_exdate_skips_cancelled_occurrence() -> None:
    # Daily for a week, with 07-03 cancelled -> that day drops out, the rest stay.
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=DAILY;COUNT=5", _dt(1), _dt(31), [_dt(3)])
    assert [s.day for _o, s, _e in occ] == [1, 2, 4, 5]


def test_exdate_matches_across_timezone_representation() -> None:
    # An EXDATE expressed in a different offset for the same instant still cancels (DST-safe).
    other_tz = timezone(timedelta(hours=2))
    exdate = datetime(2026, 7, 3, 11, 0, tzinfo=other_tz)  # == 09:00 UTC
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=DAILY;COUNT=5", _dt(1), _dt(31), [exdate])
    assert [s.day for _o, s, _e in occ] == [1, 2, 4, 5]


def test_exdate_for_non_matching_date_is_ignored() -> None:
    occ = expand_occurrences(_dt(1), _dt(1, 10), "FREQ=DAILY;COUNT=3", _dt(1), _dt(31), [_dt(9)])
    assert [s.day for _o, s, _e in occ] == [1, 2, 3]


def test_is_occurrence_accepts_real_and_rejects_fake() -> None:
    assert is_occurrence(_dt(1), "FREQ=WEEKLY", _dt(8))  # one week later
    assert not is_occurrence(_dt(1), "FREQ=WEEKLY", _dt(9))  # not on the weekly cadence


def test_override_moves_a_single_occurrence() -> None:
    from app.modules.calendar.expand import occurrence_key

    # Daily 09:00-10:00; move the 07-02 instance to 14:00-15:00. Others keep their rule time.
    overrides = {occurrence_key(_dt(2)): (_dt(2, 14), _dt(2, 15))}
    occ = expand_occurrences(
        _dt(1), _dt(1, 10), "FREQ=DAILY;COUNT=3", _dt(1), _dt(31), None, "UTC", overrides
    )
    # original_start stays the rule instant; effective start/end reflect the move.
    assert [(o.day, s.hour) for o, s, _e in occ] == [(1, 9), (2, 14), (3, 9)]
    moved = occ[1]
    assert moved[0] == _dt(2)  # original_start = the rule key
    assert moved[1] == _dt(2, 14) and moved[2] == _dt(2, 15)


def test_override_respects_window_on_effective_time() -> None:
    from app.modules.calendar.expand import occurrence_key

    # Move 07-02's instance out to 07-20; with a window ending 07-05 it drops out (effective time).
    overrides = {occurrence_key(_dt(2)): (_dt(20, 14), _dt(20, 15))}
    occ = expand_occurrences(
        _dt(1), _dt(1, 10), "FREQ=DAILY;COUNT=3", _dt(1), _dt(5, 23), None, "UTC", overrides
    )
    assert [o.day for o, _s, _e in occ] == [1, 3]
