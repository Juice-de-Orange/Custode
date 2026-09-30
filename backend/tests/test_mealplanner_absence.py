"""Unit tests for the absence->weekday mapping (Synergie S-01, ADR-0054) — pure, no DB."""

from __future__ import annotations

from datetime import UTC, date, datetime

from app.modules.mealplanner.absence import absence_weekdays

_MONDAY = date(2026, 6, 22)  # a Monday


def _dt(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, minute, tzinfo=UTC)


def test_no_intervals_is_empty() -> None:
    assert absence_weekdays([], week_start=_MONDAY) == []


def test_single_day_absence_maps_to_its_weekday() -> None:
    # Wednesday 2026-06-24 all day -> index 2.
    assert absence_weekdays([(_dt(24, 9), _dt(24, 17))], week_start=_MONDAY) == [2]


def test_multi_day_absence_spans_several_weekdays() -> None:
    # Tue 06-23 .. Thu 06-25 -> indices 1,2,3.
    assert absence_weekdays([(_dt(23), _dt(25, 12))], week_start=_MONDAY) == [1, 2, 3]


def test_midnight_end_is_half_open() -> None:
    # Tuesday 00:00 -> Wednesday 00:00 exactly: covers only Tuesday (index 1), not Wednesday.
    assert absence_weekdays([(_dt(23), _dt(24))], week_start=_MONDAY) == [1]


def test_intervals_outside_the_week_are_ignored() -> None:
    # The Monday of the following week (06-29) is out of this week's range.
    assert absence_weekdays([(_dt(29), _dt(29, 12))], week_start=_MONDAY) == []


def test_overlapping_intervals_are_deduped_and_sorted() -> None:
    spans = [(_dt(25, 8), _dt(25, 10)), (_dt(23), _dt(23, 23)), (_dt(25, 14), _dt(25, 16))]
    assert absence_weekdays(spans, week_start=_MONDAY) == [1, 3]


def test_sunday_boundary_is_covered() -> None:
    # Sunday 2026-06-28 -> index 6 (last day of the week).
    assert absence_weekdays([(_dt(28, 6), _dt(28, 8))], week_start=_MONDAY) == [6]
