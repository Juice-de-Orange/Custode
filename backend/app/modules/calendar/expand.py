"""RRULE occurrence expansion (KONZEPT §5.11, ADR-0041/0047). Pure — no DB — so it is unit-testable
without Docker. Uses ``dateutil.rrule`` (RFC 5545). A recurring event's stored ``starts_at``/
``ends_at`` define the **first** occurrence (a UTC instant) and the duration.

DST-correctness (ADR-0047): a series is anchored in its **own time zone** (``tzid``), not in UTC, so
a "weekly 09:00 Vienna" event stays at 09:00 wall-clock across the spring/autumn DST switch and only
its UTC offset shifts. Expansion is always windowed and hard-capped to avoid runaway series."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dateutil.rrule import rrulestr

MAX_OCCURRENCES = 366  # hard cap per series per window (a daily rule over a year)


def is_valid_rrule(rrule: str, *, dtstart: datetime) -> bool:
    """True if ``rrule`` parses as an RFC-5545 recurrence rule (used to 422 a bad rule)."""
    try:
        rrulestr(rrule, dtstart=dtstart)
    except (ValueError, TypeError):
        return False
    return True


def is_valid_tzid(tzid: str) -> bool:
    """True if ``tzid`` is a known IANA time zone (used to 422 a bad zone on create/update)."""
    try:
        ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def _zone(tzid: str) -> ZoneInfo:
    """Resolve an IANA zone, falling back to UTC so a bad/unknown tzid never breaks expansion."""
    try:
        return ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def as_utc_instant(dt: datetime) -> datetime:
    """Normalise to a UTC instant so two tz-aware datetimes for the same moment compare equal
    regardless of their stored offset (DST-safe)."""
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC)


def occurrence_key(dt: datetime) -> str:
    """Stable string key for an occurrence's original start (UTC instant) — used to key EXDATE-less
    single-occurrence overrides (moved instances)."""
    return as_utc_instant(dt).isoformat()


def is_occurrence(
    starts_at: datetime, rrule: str, candidate: datetime, *, tzid: str = "UTC"
) -> bool:
    """True if ``candidate`` is a genuine occurrence start (instant equality). Anchored in ``tzid``
    so DST-shifted occurrences still match. Used to reject cancelling a phantom date."""
    rule = rrulestr(rrule, dtstart=starts_at.astimezone(_zone(tzid)))
    target = as_utc_instant(candidate)
    bracket = timedelta(seconds=1)  # tolerate sub-second representation drift, stay exact
    for occ_start in rule.between(candidate - bracket, candidate + bracket, inc=True):
        if as_utc_instant(occ_start) == target:
            return True
    return False


def expand_occurrences(
    starts_at: datetime,
    ends_at: datetime,
    rrule: str | None,
    frm: datetime | None,
    to: datetime | None,
    exdates: list[datetime] | None = None,
    tzid: str = "UTC",
    overrides: dict[str, tuple[datetime, datetime]] | None = None,
) -> list[tuple[datetime, datetime, datetime]]:
    """Concrete ``(original_start, start, end)`` occurrences (UTC) within ``[frm, to]`` (each bound
    optional). ``original_start`` is the rule-generated instant (the EXDATE/override key); ``start``
    and ``end`` are the effective times — equal to the original unless an override moved them (S10).

    Non-recurring (``rrule`` None): the single event if it overlaps the window, else nothing.
    Recurring: every RRULE occurrence **anchored in ``tzid``** (wall-clock stable across DST) whose
    effective interval overlaps the window, duration preserved, capped at ``MAX_OCCURRENCES``.
    An ``exdates`` match is skipped; an ``overrides`` key replaces the occurrence's time."""
    duration = ends_at - starts_at

    if not rrule:
        if (to is None or starts_at <= to) and (frm is None or ends_at >= frm):
            return [(starts_at, starts_at, ends_at)]
        return []

    excluded = {as_utc_instant(dt) for dt in exdates} if exdates else set()
    moved = overrides or {}
    rule = rrulestr(rrule, dtstart=starts_at.astimezone(_zone(tzid)))
    window_start = frm if frm is not None else starts_at
    window_end = to if to is not None else window_start + timedelta(days=90)
    out: list[tuple[datetime, datetime, datetime]] = []
    # Start the scan one duration early so an occurrence that begins before ``frm`` but still runs
    # into the window is not missed; then apply the precise overlap test. Occurrences come out in
    # ``tzid``; normalise each to a UTC instant for output and comparison.
    for occ_local in rule.between(window_start - duration, window_end, inc=True):
        orig_start = as_utc_instant(occ_local)
        if orig_start in excluded:
            continue
        override = moved.get(occurrence_key(orig_start))
        if override is not None:
            occ_start, occ_end = as_utc_instant(override[0]), as_utc_instant(override[1])
        else:
            occ_start, occ_end = orig_start, orig_start + duration
        if frm is not None and occ_end < frm:
            continue
        if to is not None and occ_start > to:
            continue
        out.append((orig_start, occ_start, occ_end))
        if len(out) >= MAX_OCCURRENCES:
            break
    return out
