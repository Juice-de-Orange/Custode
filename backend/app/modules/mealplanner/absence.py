"""Map absence intervals to the weekdays they cover (Synergie S-01, ADR-0054). Pure, DB-free and
deterministic — the testable core of the „du bist abwesend"-Hinweis in the week grid. Day boundaries
are compared in **UTC** (a documented simplification: absences are usually all-day/multi-day)."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, time, timedelta


def absence_weekdays(
    intervals: Iterable[tuple[datetime, datetime]], *, week_start: date
) -> list[int]:
    """Weekday indices (0 = Monday, 6 = Sunday) of ``week_start``'s week that any ``[start, end)``
    interval overlaps. Sorted and distinct. ``week_start`` must be the Monday; intervals are
    timezone-aware (UTC in practice). Half-open overlap: an interval ending exactly at midnight does
    not bleed into the next day."""
    spans = list(intervals)
    days: list[int] = []
    for d in range(7):
        day_start = datetime.combine(week_start + timedelta(days=d), time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
        if any(start < day_end and end > day_start for start, end in spans):
            days.append(d)
    return days
