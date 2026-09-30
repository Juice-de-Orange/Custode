"""Property tests for the soft value-decay of overdue tasks (KONZEPT §5.9), pure logic, no DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from app.modules.tasks.decay import FLOOR, effective_points

_NOW = datetime(2026, 6, 23, 12, 0, tzinfo=UTC)


@given(
    base=st.integers(min_value=1, max_value=100000),
    days=st.integers(min_value=0, max_value=400),
)
def test_decay_within_bounds(base: int, days: int) -> None:
    """The effective award is always within [floor*base, base] — never more than base, never below
    50 % (KONZEPT §5.9: sanfter Verfall, keine Strafe)."""
    due = _NOW - timedelta(days=days)
    eff = effective_points(base, due, _NOW)
    assert eff <= base
    assert eff >= round(base * FLOOR) - 1  # rounding tolerance at the floor


@given(base=st.integers(min_value=1, max_value=100000), days=st.integers(min_value=0, max_value=50))
def test_decay_is_monotonic_non_increasing(base: int, days: int) -> None:
    """More days overdue never increases the award."""
    earlier = effective_points(base, _NOW - timedelta(days=days), _NOW)
    later = effective_points(base, _NOW - timedelta(days=days + 1), _NOW)
    assert later <= earlier


@given(base=st.integers(min_value=1, max_value=100000))
def test_no_deadline_or_on_time_is_full(base: int) -> None:
    """No deadline, or not yet overdue, pays the full base."""
    assert effective_points(base, None, _NOW) == base
    assert effective_points(base, _NOW + timedelta(hours=1), _NOW) == base
    assert effective_points(base, _NOW, _NOW) == base  # exactly due, not overdue


def test_concrete_examples() -> None:
    """A 10-point task: 1 day overdue -> 9, 3 days -> 7, 6+ days -> floored at 5."""
    assert effective_points(10, _NOW - timedelta(days=1), _NOW) == 9
    assert effective_points(10, _NOW - timedelta(days=3), _NOW) == 7
    assert effective_points(10, _NOW - timedelta(days=6), _NOW) == 5
    assert effective_points(10, _NOW - timedelta(days=100), _NOW) == 5  # never below the floor
    # less than a full day overdue does not decay yet
    assert effective_points(10, _NOW - timedelta(hours=23), _NOW) == 10
