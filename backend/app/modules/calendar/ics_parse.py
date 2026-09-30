"""iCalendar (RFC 5545) parsing for ICS import (KONZEPT §5.11, ADR-0044). Pure — no DB — so it is
unit-testable without Docker (mirror of the ``ics.py`` renderer). Best-effort subset that covers the
common Google/Nextcloud/Apple exports: UTC (``Z``) and ``TZID=`` date-times, ``VALUE=DATE`` all-day
events, ``RRULE``, ``EXDATE`` and the folded/escaped TEXT encoding. Unknown time zones fall back to
UTC rather than failing the whole import."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class ParsedIcsEvent:
    """One VEVENT reduced to the fields the calendar stores. ``ends_at`` is always populated (a
    timed event with no DTEND defaults to its start; an all-day event to the next day)."""

    title: str
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    location: str | None = None
    description: str | None = None
    rrule: str | None = None
    exdates: list[datetime] = field(default_factory=list)
    uid: str | None = None
    # P9-S3 (CalDAV pull-sync) additions — defaults keep the ICS-import behaviour unchanged.
    # TRANSP:TRANSPARENT marks a non-blocking event (birthdays) -> maps to ``busy=False``.
    transparent: bool = False
    # STATUS:CANCELLED — the sync treats it like a remotely deleted event.
    cancelled: bool = False
    # Raw RECURRENCE-ID value: this VEVENT is a moved single occurrence of the series sharing its
    # UID. The sync keeps only the master (recurrence_id is None) — naive UID-dedup would
    # otherwise drop or double the series (documented gap: overrides are not mirrored yet).
    recurrence_id: str | None = None
    # IANA zone of DTSTART when zoneinfo could resolve it (None for UTC/date-only/floating/unknown
    # zones). Preserving it anchors mirrored series DST-correctly (ADR-0047).
    tzid: str | None = None


def _unfold(text: str) -> list[str]:
    """Undo RFC-5545 line folding: a CRLF followed by a space or tab continues the previous line."""
    out: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _unescape(value: str) -> str:
    """Reverse the TEXT escaping of RFC-5545 §3.3.11."""
    out: list[str] = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"n": "\n", "N": "\n", "\\": "\\", ";": ";", ",": ","}.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _split_prop(line: str) -> tuple[str, dict[str, str], str] | None:
    """Split ``NAME;PARAM=v;P2=v2:VALUE`` into (name, params, value). None if there is no colon."""
    colon = line.find(":")
    if colon == -1:
        return None
    head, value = line[:colon], line[colon + 1 :]
    parts = head.split(";")
    name = parts[0].upper()
    params: dict[str, str] = {}
    for param in parts[1:]:
        if "=" in param:
            key, val = param.split("=", 1)
            params[key.upper()] = val
    return name, params, value


def _parse_dt(value: str, params: dict[str, str]) -> tuple[datetime, bool, str | None]:
    """Parse a DTSTART/DTEND/EXDATE value to (aware-UTC datetime, is_date_only, resolved_tzid).

    ``VALUE=DATE`` -> midnight UTC, all-day. A ``Z`` suffix is UTC; a ``TZID`` is resolved via
    zoneinfo (unknown zone -> UTC); a bare local time is treated as UTC (floating). The third
    element is the IANA zone name when zoneinfo resolved it, else None (P9-S3: the sync anchors
    mirrored series in it, ADR-0047)."""
    if params.get("VALUE") == "DATE" or (len(value) == 8 and "T" not in value):
        day = datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
        return day, True, None
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC), False, None
    naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    tzid = params.get("TZID")
    if tzid:
        try:
            return naive.replace(tzinfo=ZoneInfo(tzid)).astimezone(UTC), False, tzid
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass  # unknown zone -> treat as UTC rather than dropping the event
    return naive.replace(tzinfo=UTC), False, None


def _parse_vevent(lines: list[str]) -> ParsedIcsEvent | None:
    """Build one event from the lines between BEGIN:VEVENT and END:VEVENT. None if it has no start
    (DTSTART is mandatory) — a defensive skip rather than a hard failure."""
    title = ""
    location: str | None = None
    description: str | None = None
    rrule: str | None = None
    uid: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day = False
    exdates: list[datetime] = []
    transparent = False
    cancelled = False
    recurrence_id: str | None = None
    tzid: str | None = None

    for line in lines:
        parsed = _split_prop(line)
        if parsed is None:
            continue
        name, params, value = parsed
        if name == "SUMMARY":
            title = _unescape(value)
        elif name == "LOCATION":
            location = _unescape(value) or None
        elif name == "DESCRIPTION":
            description = _unescape(value) or None
        elif name == "RRULE":
            rrule = value.strip() or None
        elif name == "UID":
            uid = value.strip() or None
        elif name == "DTSTART":
            starts_at, all_day, tzid = _parse_dt(value, params)
        elif name == "DTEND":
            ends_at, _, _ = _parse_dt(value, params)
        elif name == "EXDATE":
            for chunk in value.split(","):
                exdates.append(_parse_dt(chunk.strip(), params)[0])
        elif name == "TRANSP":
            transparent = value.strip().upper() == "TRANSPARENT"
        elif name == "STATUS":
            cancelled = value.strip().upper() == "CANCELLED"
        elif name == "RECURRENCE-ID":
            recurrence_id = value.strip() or None

    if starts_at is None:
        return None
    if ends_at is None:
        ends_at = starts_at + timedelta(days=1) if all_day else starts_at
    return ParsedIcsEvent(
        title=title or "(ohne Titel)",
        starts_at=starts_at,
        ends_at=ends_at,
        all_day=all_day,
        location=location,
        description=description,
        rrule=rrule,
        exdates=exdates,
        uid=uid,
        transparent=transparent,
        cancelled=cancelled,
        recurrence_id=recurrence_id,
        tzid=tzid,
    )


def parse_ics(text: str) -> list[ParsedIcsEvent]:
    """Parse every VEVENT in an iCalendar document into ``ParsedIcsEvent``. Malformed events (no
    DTSTART) are skipped, not fatal — a real export may carry the odd unparseable block."""
    events: list[ParsedIcsEvent] = []
    block: list[str] | None = None
    for line in _unfold(text):
        upper = line.strip().upper()
        if upper == "BEGIN:VEVENT":
            block = []
        elif upper == "END:VEVENT":
            if block is not None:
                event = _parse_vevent(block)
                if event is not None:
                    events.append(event)
            block = None
        elif block is not None:
            block.append(line)
    return events
