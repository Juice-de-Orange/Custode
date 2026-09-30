"""Write-back rendering/patching (P9-S4, ADR-0080). Pure — no DB, no network.

Two write paths, two tools:

* **Create** (``render_single_vevent``): the event is ours entirely, so a full render with a
  caller-supplied UID is lossless. Unlike the feed renderer it emits the correct all-day form
  (``VALUE=DATE``) and ``TRANSP:TRANSPARENT`` for non-blocking events, and no ``METHOD`` /
  ``X-WR-CALNAME`` (CalDAV resources must not carry METHOD, RFC 4791 §4.1).
* **Edit** (``patch_vevent``): NEVER re-render a foreign VEVENT — the mirror stores only a
  subset of its properties, so a re-render would strip VALARMs, ATTENDEEs and X-props from the
  remote event. Instead the freshly fetched raw document is patched surgically: only the
  changed property lines are replaced/inserted/removed; every other physical line (including
  its original folding) stays byte-identical. Line endings are normalised to CRLF (RFC 5545).

``SEQUENCE``/``DTSTAMP`` are deliberately left untouched on edits (no iTIP scheduling
semantics — documented gap, ADR-0080)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from zoneinfo import ZoneInfo

from app.modules.calendar.ics import _PRODID, _escape, _stamp


class VeventNotFoundError(Exception):
    """The target UID's master VEVENT is absent from the document — the remote content changed
    under us; the service maps this to the same conflict answer as a remote 412."""


_MAX_OCTETS = 75


def _fold(line: str) -> list[str]:
    """RFC-5545 §3.1 folding: physical lines of at most 75 octets; continuation lines start
    with one space (which counts toward their 75). Never splits inside a UTF-8 sequence."""
    data = line.encode("utf-8")
    if len(data) <= _MAX_OCTETS:
        return [line]
    out: list[str] = []
    start = 0
    first = True
    while start < len(data):
        limit = _MAX_OCTETS if first else _MAX_OCTETS - 1  # continuation loses 1 octet to " "
        end = min(start + limit, len(data))
        while end < len(data) and (data[end] & 0xC0) == 0x80:  # mid-sequence -> back up
            end -= 1
        chunk = data[start:end].decode("utf-8")
        out.append(chunk if first else " " + chunk)
        start = end
        first = False
    return out


def _date_utc(dt: datetime) -> str:
    aware = dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y%m%d")


def render_single_vevent(
    *,
    uid: str,
    dtstamp: datetime,
    title: str,
    description: str | None,
    location: str | None,
    starts_at: datetime,
    ends_at: datetime,
    all_day: bool,
    busy: bool,
    rrule: str | None,
    exdates: list[datetime],
) -> str:
    """One VEVENT in its own VCALENDAR, ready to PUT as a new CalDAV resource (create path;
    UTC-anchored — the service rejects non-UTC tzids on create, E6/ADR-0080)."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(dtstamp)}",
    ]
    if all_day:
        lines.append(f"DTSTART;VALUE=DATE:{_date_utc(starts_at)}")
        lines.append(f"DTEND;VALUE=DATE:{_date_utc(ends_at)}")
    else:
        lines.append(f"DTSTART:{_stamp(starts_at)}")
        lines.append(f"DTEND:{_stamp(ends_at)}")
    lines.append(f"SUMMARY:{_escape(title)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if not busy:
        lines.append("TRANSP:TRANSPARENT")
    if rrule:
        lines.append(f"RRULE:{rrule}")
        for exdate in exdates:
            lines.append(f"EXDATE:{_stamp(exdate)}")
    lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    folded: list[str] = []
    for line in lines:
        folded.extend(_fold(line))
    return "\r\n".join(folded) + "\r\n"


def build_patch_changes(
    *, changed: set[str], eff: dict[str, object], tzid: str
) -> dict[str, str | None]:
    """Map changed mirror fields to complete (unfolded) property lines for ``patch_vevent``.
    ``None`` removes the property. Any time/all-day change rewrites BOTH DTSTART and DTEND —
    for a non-UTC ``tzid`` in the wall-clock ``;TZID=`` form (the matching VTIMEZONE already
    lives in the remote document and survives the patch, E8). Clearing the RRULE also drops
    every EXDATE (meaningless without a rule)."""
    changes: dict[str, str | None] = {}
    if "title" in changed:
        changes["SUMMARY"] = f"SUMMARY:{_escape(str(eff['title']))}"
    if "description" in changed:
        description = eff["description"]
        changes["DESCRIPTION"] = f"DESCRIPTION:{_escape(str(description))}" if description else None
    if "location" in changed:
        location = eff["location"]
        changes["LOCATION"] = f"LOCATION:{_escape(str(location))}" if location else None
    if {"starts_at", "ends_at", "all_day"} & changed:
        starts = cast(datetime, eff["starts_at"])
        ends = cast(datetime, eff["ends_at"])
        if eff["all_day"]:
            changes["DTSTART"] = f"DTSTART;VALUE=DATE:{_date_utc(starts)}"
            changes["DTEND"] = f"DTEND;VALUE=DATE:{_date_utc(ends)}"
        elif tzid != "UTC":
            zone = ZoneInfo(tzid)
            local_start = starts.astimezone(zone).strftime("%Y%m%dT%H%M%S")
            local_end = ends.astimezone(zone).strftime("%Y%m%dT%H%M%S")
            changes["DTSTART"] = f"DTSTART;TZID={tzid}:{local_start}"
            changes["DTEND"] = f"DTEND;TZID={tzid}:{local_end}"
        else:
            changes["DTSTART"] = f"DTSTART:{_stamp(starts)}"
            changes["DTEND"] = f"DTEND:{_stamp(ends)}"
    if "busy" in changed:
        changes["TRANSP"] = "TRANSP:OPAQUE" if eff["busy"] else "TRANSP:TRANSPARENT"
    if "rrule" in changed:
        rrule = eff["rrule"]
        if rrule:
            changes["RRULE"] = f"RRULE:{rrule}"
        else:
            changes["RRULE"] = None
            changes["EXDATE"] = None
    return changes


def _prop_name(text: str) -> str:
    head = text.split(":", 1)[0]
    return head.split(";", 1)[0].strip().upper()


def patch_vevent(ics_text: str, *, uid: str, changes: dict[str, str | None]) -> str:
    """Surgically apply ``changes`` to the master VEVENT (matching ``uid``, no RECURRENCE-ID)
    of a raw iCalendar document. Properties are located on unfolded logical lines but spliced
    over their physical line ranges, so untouched lines — VALARM blocks, ATTENDEEs, X-props,
    VTIMEZONEs, override VEVENTs — keep their exact bytes (modulo CRLF normalisation).
    Properties inside nested components (VALARM's own DESCRIPTION) are never touched.
    Idempotent. Raises ``VeventNotFoundError`` when the UID's master VEVENT is missing."""
    physical = ics_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while physical and physical[-1] == "":
        physical.pop()

    # Logical lines with their physical range [start, end).
    logical: list[tuple[int, int, str]] = []
    for i, raw in enumerate(physical):
        if raw[:1] in (" ", "\t") and logical:
            s, _e, t = logical[-1]
            logical[-1] = (s, i + 1, t + raw[1:])
        else:
            logical.append((i, i + 1, raw))

    # Locate the target VEVENT block (logical indices of BEGIN/END), skipping overrides.
    target: tuple[int, int] | None = None
    i = 0
    n = len(logical)
    while i < n:
        if logical[i][2].strip().upper() != "BEGIN:VEVENT":
            i += 1
            continue
        depth = 0
        uid_value: str | None = None
        has_recurrence_id = False
        end_index: int | None = None
        j = i + 1
        while j < n:
            upper = logical[j][2].strip().upper()
            if upper == "END:VEVENT" and depth == 0:
                end_index = j
                break
            if upper.startswith("BEGIN:"):
                depth += 1
            elif upper.startswith("END:"):
                depth -= 1
            elif depth == 0:
                name = _prop_name(logical[j][2])
                if name == "UID":
                    uid_value = logical[j][2].split(":", 1)[1].strip()
                elif name == "RECURRENCE-ID":
                    has_recurrence_id = True
            j += 1
        if end_index is None:
            break  # malformed tail — fall through to not-found
        if uid_value == uid and not has_recurrence_id:
            target = (i, end_index)
            break
        i = end_index + 1
    if target is None:
        raise VeventNotFoundError()
    block_start, block_end = target

    # Build the edit plan over physical ranges (depth-0 properties of the target block only).
    replaces: dict[int, tuple[int, list[str]]] = {}  # phys_start -> (phys_end, new lines)
    delete_phys: set[int] = set()
    inserts: list[str] = []
    for prop, new_line in changes.items():
        hits: list[int] = []
        depth = 0
        for k in range(block_start + 1, block_end):
            upper = logical[k][2].strip().upper()
            if upper.startswith("BEGIN:"):
                depth += 1
                continue
            if upper.startswith("END:"):
                depth -= 1
                continue
            if depth == 0 and _prop_name(logical[k][2]) == prop:
                hits.append(k)
        if new_line is None:
            for k in hits:
                delete_phys.update(range(logical[k][0], logical[k][1]))
        elif hits:
            first, *rest = hits
            replaces[logical[first][0]] = (logical[first][1], _fold(new_line))
            for k in rest:  # e.g. several EXDATE lines collapse into the one new value
                delete_phys.update(range(logical[k][0], logical[k][1]))
        else:
            inserts.extend(_fold(new_line))

    end_vevent_phys = logical[block_end][0]
    out: list[str] = []
    i = 0
    while i < len(physical):
        if i == end_vevent_phys and inserts:
            out.extend(inserts)
            inserts = []
        if i in replaces:
            phys_end, new_lines = replaces[i]
            out.extend(new_lines)
            i = phys_end
            continue
        if i in delete_phys:
            i += 1
            continue
        out.append(physical[i])
        i += 1
    return "\r\n".join(out) + "\r\n"
