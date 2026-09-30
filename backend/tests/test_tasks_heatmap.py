"""Unit tests for the room-heatmap status thresholds (KONZEPT §5.9), pure logic, no DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.modules.tasks.heatmap import room_status

_NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


def test_never_done_is_red() -> None:
    assert room_status(None, decay_days=7, now=_NOW) == "red"


def test_fresh_is_green() -> None:
    # done 1 day ago, window 10 days -> ratio 0.1 -> green
    assert room_status(_NOW - timedelta(days=1), decay_days=10, now=_NOW) == "green"


def test_aging_is_amber() -> None:
    # done 6 days ago, window 10 -> ratio 0.6 -> amber
    assert room_status(_NOW - timedelta(days=6), decay_days=10, now=_NOW) == "amber"


def test_overdue_is_red() -> None:
    # done 12 days ago, window 10 -> ratio 1.2 -> red
    assert room_status(_NOW - timedelta(days=12), decay_days=10, now=_NOW) == "red"


def test_thresholds_at_boundaries() -> None:
    # exactly 50% -> amber (not green); exactly 100% -> red
    assert room_status(_NOW - timedelta(days=5), decay_days=10, now=_NOW) == "amber"
    assert room_status(_NOW - timedelta(days=10), decay_days=10, now=_NOW) == "red"
