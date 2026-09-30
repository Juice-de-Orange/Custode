"""Unit tests for iCalendar rendering (KONZEPT §5.11, ADR-0042) — pure, no DB, no Docker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.modules.calendar.ics import render_ics
from app.modules.calendar.models import CalendarEvent


def _event(**kw: object) -> CalendarEvent:
    ev = CalendarEvent(
        title=kw.get("title", "Termin"),
        starts_at=kw.get("starts_at", datetime(2026, 7, 1, 9, 0, tzinfo=UTC)),
        ends_at=kw.get("ends_at", datetime(2026, 7, 1, 10, 0, tzinfo=UTC)),
        location=kw.get("location"),
        description=kw.get("description"),
        rrule=kw.get("rrule"),
        exdates=kw.get("exdates", []),
        overrides=kw.get("overrides", {}),
    )
    ev.id = uuid.uuid4()
    ev.updated_at = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    return ev


def test_renders_vcalendar_envelope() -> None:
    ics = render_ics([], name="Custode")
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert "VERSION:2.0" in ics
    assert "X-WR-CALNAME:Custode" in ics
    assert ics.rstrip().endswith("END:VCALENDAR")


def test_renders_a_basic_event() -> None:
    ics = render_ics([_event(title="Zahnarzt", location="Praxis")], name="Custode")
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:Zahnarzt" in ics
    assert "DTSTART:20260701T090000Z" in ics
    assert "DTEND:20260701T100000Z" in ics
    assert "LOCATION:Praxis" in ics
    assert "@custode" in ics  # UID


def test_recurring_event_carries_rrule() -> None:
    ics = render_ics([_event(rrule="FREQ=WEEKLY;BYDAY=MO")], name="Custode")
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO" in ics


def test_cancelled_occurrences_emit_exdate() -> None:
    ics = render_ics(
        [_event(rrule="FREQ=DAILY", exdates=[datetime(2026, 7, 3, 9, 0, tzinfo=UTC)])],
        name="Custode",
    )
    assert "EXDATE:20260703T090000Z" in ics


def test_moved_occurrence_emits_recurrence_id_vevent() -> None:
    ics = render_ics(
        [
            _event(
                rrule="FREQ=DAILY",
                overrides={
                    "2026-07-03T09:00:00+00:00": {
                        "starts_at": "2026-07-03T14:00:00+00:00",
                        "ends_at": "2026-07-03T15:00:00+00:00",
                    }
                },
            )
        ],
        name="Custode",
    )
    assert "RECURRENCE-ID:20260703T090000Z" in ics
    assert "DTSTART:20260703T140000Z" in ics


def test_text_values_are_escaped() -> None:
    ics = render_ics([_event(title="Kino, Essen; danach", description="A\nB")], name="Custode")
    assert "SUMMARY:Kino\\, Essen\\; danach" in ics
    assert "DESCRIPTION:A\\nB" in ics


def test_naive_datetime_is_treated_as_utc() -> None:
    ics = render_ics([_event(starts_at=datetime(2026, 7, 1, 9, 0))], name="Custode")
    assert "DTSTART:20260701T090000Z" in ics
