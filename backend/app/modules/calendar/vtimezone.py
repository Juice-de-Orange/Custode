"""VTIMEZONE generation for the ICS feed (RFC 5545 §3.6.5, ADR-0082). Pure — no DB, no I/O.

A recurring event stored as "Montag 09:00 Europe/Vienna" cannot be expressed correctly in UTC:
``DTSTART:...070000Z`` + ``RRULE:FREQ=WEEKLY`` means "07:00 UTC forever", which becomes 08:00
local once the clocks change. The RFC's answer is a local ``DTSTART;TZID=`` plus a VTIMEZONE that
tells the subscriber what that zone does — and that is what this module builds.

**Explicit transitions, not inferred rules.** The obvious shortcut is to emit
``RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU`` and hope the zone follows the EU pattern. It usually
does — until it doesn't (zones change their rules, and several never matched the pattern). A
wrong rule is worse than no feature: it silently shifts appointments by an hour for years. So the
transitions are **sampled from the tz database** and emitted as explicit ``RDATE`` entries over a
bounded window. Verbose, but it cannot be subtly wrong: whatever ``zoneinfo`` knows is what the
subscriber gets.

The window is bounded because an unbounded VTIMEZONE would grow without limit; subscribers
re-fetch the feed, so a rolling window stays accurate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

#: How far around "now" transitions are emitted. One year back so an already-synced past event
#: still resolves, five forward so a yearly series stays correct between feed refreshes.
YEARS_BACK = 1
YEARS_FORWARD = 5

#: Sampling step for the transition scan. Offsets change at most twice a year in practice; a day
#: is far finer than needed and keeps a whole window under ~2200 cheap lookups.
_STEP = timedelta(days=1)


def _offset_seconds(zone: ZoneInfo, instant: datetime) -> int:
    """Offset of ``zone`` at a UTC ``instant``. Scanning in UTC — not in naive local time —
    matters: around a transition the local clock is ambiguous or skips entirely, so a local scan
    cannot name the moment unambiguously."""
    offset = instant.astimezone(zone).utcoffset()
    return int(offset.total_seconds()) if offset is not None else 0


def _dst_seconds(zone: ZoneInfo, instant: datetime) -> int:
    dst = instant.astimezone(zone).dst()
    return int(dst.total_seconds()) if dst is not None else 0


def _format_offset(seconds: int) -> str:
    """UTC offset in the ``+HHMM`` form RFC 5545 wants (``-0530`` etc.)."""
    sign = "-" if seconds < 0 else "+"
    total = abs(seconds) // 60
    return f"{sign}{total // 60:02d}{total % 60:02d}"


def _find_transition(zone: ZoneInfo, low: datetime, high: datetime) -> datetime:
    """Binary-search the exact UTC instant at which the offset changes.

    Narrowing to the second matters: a subscriber applies the onset literally, so a value rounded
    to the day would move every appointment on that day by an hour."""
    base = _offset_seconds(zone, low)
    while high - low > timedelta(seconds=1):
        mid = low + (high - low) / 2
        if _offset_seconds(zone, mid) == base:
            low = mid
        else:
            high = mid
    return high.replace(microsecond=0)


def _onset_local(instant: datetime, offset_from: int) -> str:
    """The onset as RFC 5545 wants it: local time in the offset **before** the change.

    Easy to get wrong and expensive when wrong — Vienna's 2026 spring transition is
    ``20260329T020000`` (02:00 CET), not ``T030000`` (the same instant seen through the *new*
    offset). A subscriber that reads the wrong onset shifts the whole day by an hour."""
    return (instant + timedelta(seconds=offset_from)).strftime("%Y%m%dT%H%M%S")


def transitions(tzid: str, *, now: datetime) -> list[tuple[datetime, int, int, bool]]:
    """Every offset change of ``tzid`` in the window, as
    ``(local_start, offset_from, offset_to, is_dst)``.

    Empty for zones without transitions (UTC and the fixed-offset zones) — the caller then emits
    a single STANDARD component, which is exactly right for them."""
    try:
        zone = ZoneInfo(tzid)
    except Exception:
        return []

    start = datetime(now.year - YEARS_BACK, 1, 1, tzinfo=UTC)
    end = datetime(now.year + YEARS_FORWARD, 1, 1, tzinfo=UTC)
    out: list[tuple[datetime, int, int, bool]] = []
    cursor = start
    previous = _offset_seconds(zone, cursor)
    while cursor < end:
        nxt = cursor + _STEP
        current = _offset_seconds(zone, nxt)
        if current != previous:
            exact = _find_transition(zone, cursor, nxt)
            out.append((exact, previous, current, _dst_seconds(zone, exact) != 0))
            previous = current
        cursor = nxt
    return out


def render_vtimezone(tzid: str, *, now: datetime | None = None) -> list[str]:
    """VTIMEZONE lines for ``tzid``. Empty list for UTC — a UTC feed needs no component at all.

    A zone without transitions in the window yields one STANDARD component with its fixed offset;
    otherwise the transitions are grouped into STANDARD/DAYLIGHT, each with explicit ``RDATE``s."""
    if tzid.upper() == "UTC":
        return []
    try:
        zone = ZoneInfo(tzid)
    except Exception:
        return []  # unknown zone: the caller already falls back to UTC rendering

    moment = now or datetime.now(UTC)
    changes = transitions(tzid, now=moment)
    lines = ["BEGIN:VTIMEZONE", f"TZID:{tzid}"]

    if not changes:
        offset = _format_offset(_offset_seconds(zone, datetime(moment.year, 1, 1, tzinfo=UTC)))
        lines += [
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            f"TZOFFSETFROM:{offset}",
            f"TZOFFSETTO:{offset}",
            "END:STANDARD",
        ]
        lines.append("END:VTIMEZONE")
        return lines

    for is_dst in (True, False):
        group = [c for c in changes if c[3] is is_dst]
        if not group:
            continue
        first_start, first_from, first_to, _ = group[0]
        block = "DAYLIGHT" if is_dst else "STANDARD"
        lines += [
            f"BEGIN:{block}",
            f"DTSTART:{_onset_local(first_start, first_from)}",
            f"TZOFFSETFROM:{_format_offset(first_from)}",
            f"TZOFFSETTO:{_format_offset(first_to)}",
        ]
        for start, offset_from, _, _ in group[1:]:
            lines.append(f"RDATE:{_onset_local(start, offset_from)}")
        lines.append(f"END:{block}")

    lines.append("END:VTIMEZONE")
    return lines
