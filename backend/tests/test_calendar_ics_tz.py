"""DST correctness of the ICS feed (P9). Pure — no DB, no Docker.

The point of these is semantic, not textual: the important claim is "a subscriber applying this
feed sees 09:00 local all year", so the strongest test expands the emitted RRULE in the emitted
zone and checks the wall-clock time — string assertions alone would happily pass on a feed that
is confidently wrong.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr

from app.modules.calendar.ics import render_ics
from app.modules.calendar.models import CalendarEvent
from app.modules.calendar.vtimezone import render_vtimezone, transitions

NOW = datetime(2026, 7, 27, tzinfo=UTC)
VIENNA = ZoneInfo("Europe/Vienna")


def _event(**over: object) -> CalendarEvent:
    base: dict[str, object] = {
        "id": uuid.uuid4(),
        "title": "Montagsrunde",
        "starts_at": datetime(2026, 1, 5, 8, 0, tzinfo=UTC),  # 09:00 Vienna (CET)
        "ends_at": datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
        "updated_at": NOW,
        "all_day": False,
        "tzid": "Europe/Vienna",
        "rrule": "FREQ=WEEKLY",
        "exdates": [],
        "overrides": {},
        "location": None,
        "description": None,
    }
    event = CalendarEvent()
    for key, value in {**base, **over}.items():
        setattr(event, key, value)
    return event


def _line(ics: str, prefix: str) -> str:
    """First matching line **inside the first VEVENT** — a VTIMEZONE has its own DTSTART, and
    grabbing that one would make these tests assert the wrong thing entirely."""
    lines = ics.split("\r\n")
    start = lines.index("BEGIN:VEVENT")
    return next(line for line in lines[start:] if line.startswith(prefix))


# --- the actual promise --------------------------------------------------------


def test_a_weekly_series_stays_at_the_same_wall_clock_across_the_dst_change() -> None:
    """The bug this fixes: as UTC, "Montag 09:00 Wien" silently became 10:00 after the March
    change. Here the emitted DTSTART+RRULE are expanded in the emitted zone and every occurrence
    must read 09:00 — spanning both the spring and the autumn transition."""
    ics = render_ics([_event()], name="Test", now=NOW)
    dtstart = _line(ics, "DTSTART")
    assert dtstart == "DTSTART;TZID=Europe/Vienna:20260105T090000"

    local_start = datetime(2026, 1, 5, 9, 0, tzinfo=VIENNA)
    occurrences = rrulestr("FREQ=WEEKLY", dtstart=local_start).between(
        datetime(2026, 1, 1, tzinfo=VIENNA), datetime(2026, 12, 31, tzinfo=VIENNA)
    )
    assert len(occurrences) > 40  # a full year of Mondays
    assert {o.astimezone(VIENNA).strftime("%H:%M") for o in occurrences} == {"09:00"}


def test_the_feed_carries_a_vtimezone_for_every_zone_it_uses() -> None:
    ics = render_ics([_event()], name="Test", now=NOW)
    assert "BEGIN:VTIMEZONE" in ics
    assert "TZID:Europe/Vienna" in ics
    # ...and it precedes the events that reference it (RFC 5545 §3.6).
    assert ics.index("BEGIN:VTIMEZONE") < ics.index("BEGIN:VEVENT")


def test_one_vtimezone_per_zone_not_per_event() -> None:
    ics = render_ics([_event(), _event(), _event()], name="Test", now=NOW)
    assert ics.count("BEGIN:VTIMEZONE") == 1


def test_the_transition_onset_is_local_time_in_the_previous_offset() -> None:
    """RFC 5545: the onset is expressed in TZOFFSETFROM. Vienna's 2026 spring change is
    02:00 CET, not 03:00 CEST — a subscriber reading the wrong one shifts that day by an hour."""
    lines = render_vtimezone("Europe/Vienna", now=NOW)
    assert "DTSTART:20250330T020000" in lines  # first DAYLIGHT onset in the window
    assert "RDATE:20260329T020000" in lines
    assert "TZOFFSETFROM:+0100" in lines
    assert "TZOFFSETTO:+0200" in lines


def test_transitions_are_exact_to_the_second() -> None:
    """Rounded to the day, every appointment on a transition day would move by an hour."""
    for instant, _, _, _ in transitions("Europe/Vienna", now=NOW):
        assert instant.second == 0 and instant.minute == 0
        # The real Vienna transitions happen at 01:00 UTC (spring) / 01:00 UTC (autumn).
        assert instant.tzinfo is not None


# --- the unchanged paths -------------------------------------------------------


def test_a_utc_event_renders_exactly_as_before() -> None:
    """Nothing about existing feeds may shift — UTC events keep the Z form and need no zone."""
    ics = render_ics([_event(tzid="UTC")], name="Test", now=NOW)
    assert _line(ics, "DTSTART") == "DTSTART:20260105T080000Z"
    assert "BEGIN:VTIMEZONE" not in ics


def test_an_unknown_zone_falls_back_to_utc_instead_of_breaking() -> None:
    ics = render_ics([_event(tzid="Mars/Olympus")], name="Test", now=NOW)
    assert _line(ics, "DTSTART").endswith("Z")
    assert "BEGIN:VTIMEZONE" not in ics


# --- all-day -------------------------------------------------------------------


def test_all_day_events_render_as_dates_not_midnight_instants() -> None:
    """A whole day is a date; as an instant subscribers showed a zero-length 00:00 appointment."""
    ics = render_ics(
        [
            _event(
                all_day=True,
                rrule=None,
                starts_at=datetime(2026, 7, 1, tzinfo=UTC),
                ends_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        ],
        name="Test",
        now=NOW,
    )
    assert _line(ics, "DTSTART") == "DTSTART;VALUE=DATE:20260701"
    # DTEND is exclusive per RFC 5545 — a one-day event ends on the next date.
    assert _line(ics, "DTEND") == "DTEND;VALUE=DATE:20260702"


# --- exceptions keep the same value type ---------------------------------------


def test_exdate_matches_dtstart_form() -> None:
    """A subscriber silently ignores an EXDATE whose value type or zone differs from DTSTART."""
    ics = render_ics(
        [_event(exdates=[datetime(2026, 1, 12, 8, 0, tzinfo=UTC)])], name="Test", now=NOW
    )
    assert _line(ics, "EXDATE") == "EXDATE;TZID=Europe/Vienna:20260112T090000"


def test_moved_occurrence_keeps_the_zone() -> None:
    moved_start = datetime(2026, 1, 12, 10, 0, tzinfo=UTC)
    ics = render_ics(
        [
            _event(
                overrides={
                    datetime(2026, 1, 12, 8, 0, tzinfo=UTC).isoformat(): {
                        "starts_at": moved_start.isoformat(),
                        "ends_at": (moved_start + timedelta(hours=1)).isoformat(),
                    }
                }
            )
        ],
        name="Test",
        now=NOW,
    )
    assert _line(ics, "RECURRENCE-ID") == "RECURRENCE-ID;TZID=Europe/Vienna:20260112T090000"
    assert "DTSTART;TZID=Europe/Vienna:20260112T110000" in ics
