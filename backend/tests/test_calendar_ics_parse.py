"""Unit tests for iCalendar import parsing (KONZEPT §5.11, ADR-0044) — pure, no DB, no Docker."""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.calendar.ics import render_ics
from app.modules.calendar.ics_parse import parse_ics
from app.modules.calendar.models import CalendarEvent


def _wrap(*vevents: str) -> str:
    body = "\r\n".join(vevents)
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//Test//EN\r\n{body}\r\nEND:VCALENDAR\r\n"


def test_parses_timed_utc_event() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:abc-1\r\nSUMMARY:Zahnarzt\r\n"
        "DTSTART:20260701T090000Z\r\nDTEND:20260701T100000Z\r\nLOCATION:Praxis\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.title == "Zahnarzt"
    assert ev.starts_at == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    assert ev.ends_at == datetime(2026, 7, 1, 10, 0, tzinfo=UTC)
    assert ev.location == "Praxis"
    assert ev.all_day is False
    assert ev.uid == "abc-1"


def test_parses_all_day_event() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:d1\r\nSUMMARY:Urlaub\r\n"
        "DTSTART;VALUE=DATE:20260701\r\nDTEND;VALUE=DATE:20260702\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.all_day is True
    assert ev.starts_at == datetime(2026, 7, 1, 0, 0, tzinfo=UTC)
    assert ev.ends_at == datetime(2026, 7, 2, 0, 0, tzinfo=UTC)


def test_parses_tzid_into_utc() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:tz1\r\nSUMMARY:Call\r\n"
        "DTSTART;TZID=Europe/Vienna:20260701T110000\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    # Vienna is UTC+2 in July -> 11:00 local == 09:00 UTC.
    assert ev.starts_at == datetime(2026, 7, 1, 9, 0, tzinfo=UTC)
    # No DTEND on a timed event -> ends == starts.
    assert ev.ends_at == ev.starts_at


def test_unknown_tzid_falls_back_to_utc() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:tz2\r\nSUMMARY:X\r\n"
        "DTSTART;TZID=Mars/Olympus:20260701T110000\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.starts_at == datetime(2026, 7, 1, 11, 0, tzinfo=UTC)


def test_parses_rrule_and_exdate() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:r1\r\nSUMMARY:Standup\r\nDTSTART:20260701T090000Z\r\n"
        "RRULE:FREQ=WEEKLY;BYDAY=WE\r\nEXDATE:20260708T090000Z,20260715T090000Z\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.rrule == "FREQ=WEEKLY;BYDAY=WE"
    assert ev.exdates == [
        datetime(2026, 7, 8, 9, 0, tzinfo=UTC),
        datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    ]


def test_unfolds_and_unescapes_text() -> None:
    # A folded DESCRIPTION (continuation line starts with a space) with escaped comma + newline.
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:f1\r\nDTSTART:20260701T090000Z\r\n"
        "SUMMARY:Kino\\, Essen\r\nDESCRIPTION:Zeile1\\nZ\r\n eile2\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.title == "Kino, Essen"
    assert ev.description == "Zeile1\nZeile2"


def test_skips_vevent_without_dtstart() -> None:
    ics = _wrap("BEGIN:VEVENT\r\nUID:bad\r\nSUMMARY:NoStart\r\nEND:VEVENT")
    assert parse_ics(ics) == []


def test_render_then_parse_round_trips() -> None:
    ev = CalendarEvent(
        title="Team Sync",
        starts_at=datetime(2026, 7, 1, 9, 0, tzinfo=UTC),
        ends_at=datetime(2026, 7, 1, 9, 30, tzinfo=UTC),
        location="Raum 2",
        description=None,
        rrule="FREQ=WEEKLY",
        exdates=[datetime(2026, 7, 8, 9, 0, tzinfo=UTC)],
    )
    import uuid

    ev.id = uuid.uuid4()
    ev.updated_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    [parsed] = parse_ics(render_ics([ev], name="Custode"))
    assert parsed.title == "Team Sync"
    assert parsed.starts_at == ev.starts_at
    assert parsed.ends_at == ev.ends_at
    assert parsed.rrule == "FREQ=WEEKLY"
    assert parsed.exdates == ev.exdates


# --- P9-S3 additions (CalDAV pull-sync fields) --------------------------------


def test_transp_transparent_is_exposed() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:t1\r\nSUMMARY:Geburtstag\r\n"
        "DTSTART;VALUE=DATE:20260701\r\nTRANSP:TRANSPARENT\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.transparent is True


def test_transp_opaque_stays_default() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:t2\r\nSUMMARY:Meeting\r\n"
        "DTSTART:20260701T090000Z\r\nTRANSP:OPAQUE\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.transparent is False


def test_status_cancelled_is_exposed() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:c1\r\nSUMMARY:Abgesagt\r\n"
        "DTSTART:20260701T090000Z\r\nSTATUS:CANCELLED\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.cancelled is True


def test_recurrence_id_is_exposed() -> None:
    # An override VEVENT shares the master's UID; the sync must be able to tell them apart.
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:s1\r\nSUMMARY:Serie\r\nDTSTART:20260701T090000Z\r\n"
        "RRULE:FREQ=WEEKLY\r\nEND:VEVENT",
        "BEGIN:VEVENT\r\nUID:s1\r\nSUMMARY:Serie (verschoben)\r\n"
        "DTSTART:20260708T110000Z\r\nRECURRENCE-ID:20260708T090000Z\r\nEND:VEVENT",
    )
    master, override = parse_ics(ics)
    assert master.recurrence_id is None
    assert override.recurrence_id == "20260708T090000Z"


def test_resolvable_tzid_is_preserved() -> None:
    # DST-correct mirroring (ADR-0047): the sync anchors the series in the source zone.
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:z1\r\nSUMMARY:Call\r\n"
        "DTSTART;TZID=Europe/Vienna:20260701T110000\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.tzid == "Europe/Vienna"


def test_unknown_tzid_yields_none() -> None:
    ics = _wrap(
        "BEGIN:VEVENT\r\nUID:z2\r\nSUMMARY:Call\r\n"
        "DTSTART;TZID=W. Custom Standard Time:20260701T110000\r\nEND:VEVENT"
    )
    [ev] = parse_ics(ics)
    assert ev.tzid is None  # time itself still parsed (UTC fallback), zone not claimed
