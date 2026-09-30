"""iCalendar (RFC 5545) rendering for the ICS subscription feed (KONZEPT §5.11, ADR-0042). Pure — no
DB — so it is unit-testable without Docker. Recurring events are emitted as a single VEVENT carrying
the RRULE; the subscriber's calendar app expands occurrences (no server-side expansion needed).

**DST correctness (P9).** The feed used to render everything as UTC, which quietly broke recurring
events: "Montag 09:00 Europe/Vienna" became ``DTSTART:...070000Z`` + ``RRULE:FREQ=WEEKLY``, i.e.
"07:00 UTC forever" — 08:00 local from the next clock change onwards. Events carrying a real
``tzid`` are now emitted as local time with ``TZID=``, accompanied by a VTIMEZONE per zone used
(``vtimezone.py``). UTC events are unchanged, so nothing about the existing behaviour shifts.

All-day events are emitted as ``VALUE=DATE`` — a whole day is a date, not a midnight instant, and
rendering it as one made subscribers show a zero-length appointment at 00:00."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.modules.calendar.models import CalendarEvent
from app.modules.calendar.vtimezone import render_vtimezone

_PRODID = "-//Custode//Calendar//DE"


def _escape(text: str) -> str:
    """Escape a TEXT value per RFC 5545 §3.3.11 (backslash, semicolon, comma, newline)."""
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _stamp(dt: datetime) -> str:
    """UTC timestamp in iCalendar basic format, e.g. 20260701T090000Z (tz-aware -> UTC)."""
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _zone_of(event: CalendarEvent) -> ZoneInfo | None:
    """The event's zone, or ``None`` when it is UTC / unknown — then the old UTC rendering applies.
    An unresolvable zone must never break the feed (E10): a slightly-off time beats a 500."""
    tzid = (event.tzid or "UTC").strip()
    if not tzid or tzid.upper() == "UTC":
        return None
    try:
        return ZoneInfo(tzid)
    except Exception:
        return None


def _local(dt: datetime, zone: ZoneInfo) -> str:
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(zone).strftime("%Y%m%dT%H%M%S")


def _date(dt: datetime, zone: ZoneInfo | None) -> str:
    """The calendar DATE an all-day event falls on, seen from its own zone."""
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return (aware.astimezone(zone) if zone else aware.astimezone(UTC)).strftime("%Y%m%d")


def _when(prop: str, dt: datetime, event: CalendarEvent, zone: ZoneInfo | None) -> str:
    """One DTSTART/DTEND/EXDATE line in the form the event's storage justifies."""
    if event.all_day:
        return f"{prop};VALUE=DATE:{_date(dt, zone)}"
    if zone is not None:
        return f"{prop};TZID={event.tzid}:{_local(dt, zone)}"
    return f"{prop}:{_stamp(dt)}"


def _vevent(event: CalendarEvent) -> list[str]:
    zone = _zone_of(event)
    # DTEND of an all-day event is exclusive per RFC 5545 — a single day ends on the NEXT date.
    end = event.ends_at + timedelta(days=1) if event.all_day else event.ends_at
    lines = [
        "BEGIN:VEVENT",
        f"UID:{event.id}@custode",
        f"DTSTAMP:{_stamp(event.updated_at)}",
        _when("DTSTART", event.starts_at, event, zone),
        _when("DTEND", end, event, zone),
        f"SUMMARY:{_escape(event.title)}",
    ]
    if event.location:
        lines.append(f"LOCATION:{_escape(event.location)}")
    if event.description:
        lines.append(f"DESCRIPTION:{_escape(event.description)}")
    if event.rrule:
        lines.append(f"RRULE:{event.rrule}")
        # Cancelled single occurrences (P5-S5): one EXDATE line so subscribers drop them too.
        for exdate in event.exdates:
            # EXDATE must match DTSTART's value type + zone, or subscribers ignore it silently.
            lines.append(_when("EXDATE", exdate, event, zone))
    lines.append("END:VEVENT")
    # Moved single occurrences (P5-S10): one extra VEVENT per override, same UID + RECURRENCE-ID
    # pointing at the original instant, so a subscriber replaces that instance with the new time.
    for orig_iso, moved in (event.overrides or {}).items():
        try:
            orig = datetime.fromisoformat(orig_iso)
            new_start = datetime.fromisoformat(moved["starts_at"])
            new_end = datetime.fromisoformat(moved["ends_at"])
        except (KeyError, TypeError, ValueError):
            continue
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.id}@custode",
            _when("RECURRENCE-ID", orig, event, zone),
            f"DTSTAMP:{_stamp(event.updated_at)}",
            _when("DTSTART", new_start, event, zone),
            _when("DTEND", new_end, event, zone),
            f"SUMMARY:{_escape(event.title)}",
            "END:VEVENT",
        ]
    return lines


def render_ics(events: Iterable[CalendarEvent], *, name: str, now: datetime | None = None) -> str:
    """Render events as a VCALENDAR. Recurring events carry their RRULE; the client expands them.
    Lines are CRLF-joined per RFC 5545.

    ``now`` only bounds the VTIMEZONE transition window (injectable for deterministic tests)."""
    materialised = list(events)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    # One VTIMEZONE per zone actually used, before the events that reference it (RFC 5545 §3.6).
    seen: set[str] = set()
    for event in materialised:
        tzid = (event.tzid or "UTC").strip()
        if tzid in seen or _zone_of(event) is None:
            continue
        seen.add(tzid)
        lines.extend(render_vtimezone(tzid, now=now))
    for event in materialised:
        lines.extend(_vevent(event))
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
