"""Pure free-slot search (KONZEPT §5.12, ADR-0046) — no DB, no I/O, so it is unit-testable without
Docker (mirror of the calendar pure-function pattern). Given the occupied intervals and a window, it
returns conflict-free slots of the requested duration inside daily working hours, each with the
machine-readable reasons that justify it (the web renders the plain-text explanation)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

MAX_SLOTS = 20  # hard cap so a wide window can never blow up the response
RAIN_WARNING_THRESHOLD = 60  # max daily precipitation probability (%) at/above which we warn

#: From this duration on, a task counts as "XL" for Synergie S-14 (Wearable-Schonung). Below it
#: the recovery hint would be noise: nobody needs to be told to postpone a ten-minute chore
#: because they slept badly. Ninety minutes is the point where a task realistically eats an
#: evening.
LONG_TASK_MINUTES = 90


@dataclass(frozen=True)
class FreeSlot:
    start: datetime
    end: datetime
    # Machine-readable justification codes (the UI maps them to localised plain text).
    reasons: list[str] = field(default_factory=list)


def merge_intervals(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    """Sort + coalesce overlapping/adjacent ``(start, end)`` intervals into disjoint busy blocks."""
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda iv: iv[0])
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # overlap or touch -> extend
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def find_free_slots(
    busy: list[tuple[datetime, datetime]],
    *,
    frm: datetime,
    to: datetime,
    duration: timedelta,
    day_start_hour: int,
    day_end_hour: int,
    max_results: int,
    absences: list[tuple[datetime, datetime]] | None = None,
    rain_by_date: dict[str, int] | None = None,
    low_recovery_dates: set[str] | None = None,
) -> list[FreeSlot]:
    """Conflict-free slots of ``duration`` within ``[frm, to]``, restricted to the daily working
    window ``[day_start_hour, day_end_hour]`` (UTC for now — tz-aware hours are a later slice). One
    slot is emitted at the start of each free gap that is long enough; results are capped.

    ``absences`` block scheduling just like busy events, but additionally tag every returned slot
    with the ``avoids_absence`` reason (the member is never offered a slot while they are away).
    ``rain_by_date`` maps an ISO date (YYYY-MM-DD) to its max precipitation probability (%); a slot
    on a day at/above ``RAIN_WARNING_THRESHOLD`` is tagged ``rain_warning`` (Synergie S-15).

    ``low_recovery_dates`` holds ISO dates on which the member's own wearable reading says they are
    run down (Synergie S-14). Slots there are tagged ``low_recovery`` — but only when ``duration``
    reaches ``LONG_TASK_MINUTES``, because the synergy is about XL tasks. The slot set itself is
    **unchanged**: no slot is dropped or reordered, so a household without wearables sees exactly
    the same suggestions. "Meiden" is realised as a visible hint the member can overrule, not as a
    silent removal — hiding options would both diverge from the base path and decide for them."""
    if duration <= timedelta(0) or frm >= to:
        return []
    cap = max(0, min(max_results, MAX_SLOTS))
    away = absences or []
    rain = rain_by_date or {}
    # Only long tasks carry the recovery hint (S-14: "XL-Tasks meiden Erschöpfungstage").
    strained = (
        low_recovery_dates or set() if duration >= timedelta(minutes=LONG_TASK_MINUTES) else set()
    )
    merged = merge_intervals([*busy, *away])
    base_reasons = ["no_conflict", "within_work_hours"]
    if away:
        base_reasons.append("avoids_absence")
    slots: list[FreeSlot] = []

    day = datetime(frm.year, frm.month, frm.day, tzinfo=frm.tzinfo)
    while day <= to and len(slots) < cap:
        win_start = max(frm, day + timedelta(hours=day_start_hour))
        win_end = min(to, day + timedelta(hours=day_end_hour))
        cursor = win_start
        for busy_start, busy_end in merged:
            if cursor >= win_end:
                break
            if busy_end <= cursor:
                continue
            if busy_start >= win_end:
                break
            if busy_start - cursor >= duration:
                slots.append(_slot(cursor, duration, base_reasons, rain, strained))
                if len(slots) >= cap:
                    break
            cursor = max(cursor, busy_end)
        if len(slots) < cap and win_end - cursor >= duration:
            slots.append(_slot(cursor, duration, base_reasons, rain, strained))
        day += timedelta(days=1)
    return slots[:cap]


def _slot(
    start: datetime,
    duration: timedelta,
    base_reasons: list[str],
    rain: dict[str, int],
    strained: set[str],
) -> FreeSlot:
    # By construction every suggested slot is within working hours and free of busy events.
    reasons = list(base_reasons)
    iso_day = start.date().isoformat()
    prob = rain.get(iso_day)
    if prob is not None and prob >= RAIN_WARNING_THRESHOLD:
        reasons.append("rain_warning")
    if iso_day in strained:
        reasons.append("low_recovery")
    return FreeSlot(start=start, end=start + duration, reasons=reasons)
