"""Unit tests for the free-slot engine (KONZEPT §5.12, ADR-0046) — pure, no DB, no Docker."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.scheduling.engine import find_free_slots, merge_intervals


def _dt(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=UTC)


def test_merge_intervals_coalesces_overlaps() -> None:
    merged = merge_intervals(
        [(_dt(1, 9), _dt(1, 10)), (_dt(1, 10), _dt(1, 11)), (_dt(1, 14), _dt(1, 15))]
    )
    assert merged == [(_dt(1, 9), _dt(1, 11)), (_dt(1, 14), _dt(1, 15))]


def test_empty_calendar_suggests_from_work_start() -> None:
    slots = find_free_slots(
        [],
        frm=_dt(1, 0),
        to=_dt(1, 23),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
    )
    assert len(slots) == 1
    assert slots[0].start == _dt(1, 7)  # first slot at the start of the working window
    assert slots[0].end == _dt(1, 8)
    assert "no_conflict" in slots[0].reasons
    assert "within_work_hours" in slots[0].reasons


def test_busy_event_pushes_slot_after_it() -> None:
    # Busy 07:00-09:00 -> the first free 1h slot starts at 09:00.
    slots = find_free_slots(
        [(_dt(1, 7), _dt(1, 9))],
        frm=_dt(1, 7),
        to=_dt(1, 12),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
    )
    assert slots[0].start == _dt(1, 9)


def test_gap_too_small_is_skipped() -> None:
    # Busy 07:00-08:30 and 09:00-12:00 -> the 08:30-09:00 gap (30m) is too small for a 1h slot;
    # the next slot is after the second block at 12:00.
    slots = find_free_slots(
        [(_dt(1, 7), _dt(1, 8, 30)), (_dt(1, 9), _dt(1, 12))],
        frm=_dt(1, 7),
        to=_dt(1, 16),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=2,
    )
    assert slots[0].start == _dt(1, 12)


def test_work_hours_bound_the_search() -> None:
    # A slot cannot start before day_start nor run past day_end.
    slots = find_free_slots(
        [],
        frm=_dt(1, 0),
        to=_dt(1, 23, 59),
        duration=timedelta(hours=2),
        day_start_hour=9,
        day_end_hour=17,
        max_results=20,
    )
    assert slots[0].start == _dt(1, 9)
    assert all(s.start >= _dt(s.start.day, 9) for s in slots)
    assert all(s.end <= _dt(s.start.day, 17) for s in slots)


def test_spans_multiple_days_until_cap() -> None:
    slots = find_free_slots(
        [],
        frm=_dt(1, 7),
        to=_dt(5, 21),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=3,
    )
    assert [s.start.day for s in slots] == [1, 2, 3]  # one per day, capped at 3


def test_absence_blocks_and_tags_reason() -> None:
    # Away 07:00-12:00 -> the first 1h slot starts at 12:00 and carries the avoids_absence reason.
    slots = find_free_slots(
        [],
        frm=_dt(1, 7),
        to=_dt(1, 16),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
        absences=[(_dt(1, 7), _dt(1, 12))],
    )
    assert slots[0].start == _dt(1, 12)
    assert "avoids_absence" in slots[0].reasons


def test_no_absence_means_no_absence_reason() -> None:
    slots = find_free_slots(
        [],
        frm=_dt(1, 7),
        to=_dt(1, 16),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
    )
    assert "avoids_absence" not in slots[0].reasons


def test_rain_day_tags_warning() -> None:
    slots = find_free_slots(
        [],
        frm=_dt(1, 7),
        to=_dt(1, 16),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
        rain_by_date={"2026-07-01": 80},
    )
    assert "rain_warning" in slots[0].reasons


def test_low_rain_probability_does_not_warn() -> None:
    slots = find_free_slots(
        [],
        frm=_dt(1, 7),
        to=_dt(1, 16),
        duration=timedelta(hours=1),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
        rain_by_date={"2026-07-01": 20},
    )
    assert "rain_warning" not in slots[0].reasons


def test_zero_duration_and_inverted_window_yield_nothing() -> None:
    assert (
        find_free_slots(
            [],
            frm=_dt(1, 7),
            to=_dt(1, 21),
            duration=timedelta(0),
            day_start_hour=7,
            day_end_hour=21,
            max_results=5,
        )
        == []
    )
    assert (
        find_free_slots(
            [],
            frm=_dt(2, 7),
            to=_dt(1, 21),
            duration=timedelta(hours=1),
            day_start_hour=7,
            day_end_hour=21,
            max_results=5,
        )
        == []
    )


# --- Wearable-Schonung (Synergie S-14, P9-S7) ---------------------------------


def _slots_for(minutes: int, low_recovery: set[str] | None) -> list[list[str]]:
    slots = find_free_slots(
        [],
        frm=_dt(1, 0),
        to=_dt(1, 23),
        duration=timedelta(minutes=minutes),
        day_start_hour=7,
        day_end_hour=21,
        max_results=5,
        low_recovery_dates=low_recovery,
    )
    return [s.reasons for s in slots]


def test_long_task_on_a_low_recovery_day_is_flagged() -> None:
    reasons = _slots_for(120, {"2026-07-01"})
    assert reasons and "low_recovery" in reasons[0]


def test_short_task_is_never_flagged() -> None:
    """S-14 is about XL tasks. Telling somebody to postpone a ten-minute chore because they
    slept badly would be noise, and this feature has to earn its interruption."""
    reasons = _slots_for(30, {"2026-07-01"})
    assert reasons and "low_recovery" not in reasons[0]


def test_a_day_without_the_signal_is_not_flagged() -> None:
    reasons = _slots_for(120, {"2026-07-02"})  # a different day
    assert reasons and "low_recovery" not in reasons[0]


def test_without_wearables_nothing_changes() -> None:
    """The base path: a household without wearables must get byte-identical suggestions."""
    assert _slots_for(120, None) == _slots_for(120, set())


def test_the_flag_never_removes_or_reorders_slots() -> None:
    """ "Meiden" is a visible hint the member can overrule, not a silent removal — hiding options
    would both diverge from the base path and decide for them."""
    plain = find_free_slots(
        [(_dt(1, 9), _dt(1, 12))],
        frm=_dt(1, 0),
        to=_dt(3, 23),
        duration=timedelta(minutes=120),
        day_start_hour=7,
        day_end_hour=21,
        max_results=10,
    )
    flagged = find_free_slots(
        [(_dt(1, 9), _dt(1, 12))],
        frm=_dt(1, 0),
        to=_dt(3, 23),
        duration=timedelta(minutes=120),
        day_start_hour=7,
        day_end_hour=21,
        max_results=10,
        low_recovery_dates={"2026-07-01"},
    )
    assert [(s.start, s.end) for s in plain] == [(s.start, s.end) for s in flagged]


def test_recovery_and_rain_hints_coexist() -> None:
    slots = find_free_slots(
        [],
        frm=_dt(1, 0),
        to=_dt(1, 23),
        duration=timedelta(minutes=120),
        day_start_hour=7,
        day_end_hour=21,
        max_results=1,
        rain_by_date={"2026-07-01": 80},
        low_recovery_dates={"2026-07-01"},
    )
    assert {"rain_warning", "low_recovery"} <= set(slots[0].reasons)
