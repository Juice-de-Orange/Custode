"""Unit tests for the write-back rendering/patching (P9-S4, ADR-0080) — pure, no Docker.
The core guarantee under test: ``patch_vevent`` touches ONLY the changed properties of the
target master VEVENT; every other byte of the remote document survives."""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.modules.calendar.ics_parse import parse_ics
from app.modules.calendar.ics_write import (
    VeventNotFoundError,
    _fold,
    build_patch_changes,
    patch_vevent,
    render_single_vevent,
)

_T0 = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
_T1 = datetime(2026, 8, 1, 10, 0, tzinfo=UTC)


def _render(**overrides: object) -> str:
    kwargs: dict = {
        "uid": "abc123",
        "dtstamp": _T0,
        "title": "Termin",
        "description": None,
        "location": None,
        "starts_at": _T0,
        "ends_at": _T1,
        "all_day": False,
        "busy": True,
        "rrule": None,
        "exdates": [],
    }
    kwargs.update(overrides)
    return render_single_vevent(**kwargs)


# --- render_single_vevent -----------------------------------------------------


def test_render_uses_caller_uid_and_no_method() -> None:
    ics = _render()
    assert "UID:abc123\r\n" in ics
    assert "METHOD" not in ics  # CalDAV resources must not carry METHOD (RFC 4791)
    assert "X-WR-CALNAME" not in ics
    assert ics.endswith("\r\n")


def test_render_all_day_uses_value_date() -> None:
    ics = _render(all_day=True, starts_at=_T0, ends_at=datetime(2026, 8, 2, tzinfo=UTC))
    assert "DTSTART;VALUE=DATE:20260801" in ics
    assert "DTEND;VALUE=DATE:20260802" in ics
    assert "T000000Z" not in ics  # the feed renderer's lossy form must not appear


def test_render_transp_only_when_not_busy() -> None:
    assert "TRANSP:TRANSPARENT" in _render(busy=False)
    assert "TRANSP" not in _render(busy=True)


def test_render_exdate_only_with_rrule() -> None:
    with_rule = _render(rrule="FREQ=WEEKLY", exdates=[datetime(2026, 8, 8, 9, 0, tzinfo=UTC)])
    assert "RRULE:FREQ=WEEKLY" in with_rule
    assert "EXDATE:20260808T090000Z" in with_rule
    without_rule = _render(rrule=None, exdates=[datetime(2026, 8, 8, 9, 0, tzinfo=UTC)])
    assert "EXDATE" not in without_rule


def test_render_folds_long_lines_multibyte_safe() -> None:
    ics = _render(title="Ä" * 60)  # 120 octets as UTF-8 -> must fold
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    # And the fold must be reversible without breaking a codepoint:
    [ev] = parse_ics(ics)
    assert ev.title == "Ä" * 60


def test_render_parse_symmetry() -> None:
    ics = _render(
        title="Kino, Essen",
        description="Zeile1\nZeile2",
        location="Saal 3",
        busy=False,
        rrule="FREQ=WEEKLY",
    )
    [ev] = parse_ics(ics)
    assert ev.title == "Kino, Essen"
    assert ev.description == "Zeile1\nZeile2"
    assert ev.location == "Saal 3"
    assert ev.transparent is True
    assert ev.rrule == "FREQ=WEEKLY"
    assert ev.starts_at == _T0 and ev.ends_at == _T1


def test_fold_boundaries() -> None:
    assert _fold("x" * 75) == ["x" * 75]  # exactly at the cap: untouched
    folded = _fold("x" * 76)
    assert folded[0] == "x" * 75 and folded[1] == " x"


# --- patch_vevent -------------------------------------------------------------

_FOREIGN = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//Nextcloud//Kalender//DE\r\n"
    "BEGIN:VTIMEZONE\r\n"
    "TZID:Europe/Vienna\r\n"
    "END:VTIMEZONE\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:remote-1\r\n"
    "DTSTAMP:20260701T000000Z\r\n"
    "SEQUENCE:4\r\n"
    "DTSTART;TZID=Europe/Vienna:20260801T110000\r\n"
    "DTEND;TZID=Europe/Vienna:20260801T120000\r\n"
    "SUMMARY:Alter Titel\r\n"
    "ATTENDEE;CN=Mitbewohner:mailto:wg@example.de\r\n"
    "X-CUSTOM-PROP;X-PARAM=1:bleibt-unangetastet-und-ist-absichtlich-eine-sehr-l\r\n"
    " ange-gefaltete-zeile\r\n"
    "BEGIN:VALARM\r\n"
    "ACTION:DISPLAY\r\n"
    "DESCRIPTION:Erinnerung\r\n"
    "TRIGGER:-PT10M\r\n"
    "END:VALARM\r\n"
    "END:VEVENT\r\n"
    "BEGIN:VEVENT\r\n"
    "UID:remote-1\r\n"
    "RECURRENCE-ID:20260808T090000Z\r\n"
    "DTSTART:20260808T110000Z\r\n"
    "SUMMARY:Verschobene Instanz\r\n"
    "END:VEVENT\r\n"
    "END:VCALENDAR\r\n"
)


def test_patch_replaces_only_the_changed_property() -> None:
    out = patch_vevent(_FOREIGN, uid="remote-1", changes={"SUMMARY": "SUMMARY:Neuer Titel"})
    assert "SUMMARY:Neuer Titel\r\n" in out
    assert "SUMMARY:Alter Titel" not in out
    # Everything foreign survives byte-identically:
    for kept in (
        "PRODID:-//Nextcloud//Kalender//DE",
        "BEGIN:VTIMEZONE\r\nTZID:Europe/Vienna\r\nEND:VTIMEZONE",
        "SEQUENCE:4",
        "DTSTART;TZID=Europe/Vienna:20260801T110000",
        "ATTENDEE;CN=Mitbewohner:mailto:wg@example.de",
        "X-CUSTOM-PROP;X-PARAM=1:bleibt-unangetastet-und-ist-absichtlich-eine-sehr-l\r\n"
        " ange-gefaltete-zeile",
        "BEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Erinnerung\r\nTRIGGER:-PT10M\r\nEND:VALARM",
        "SUMMARY:Verschobene Instanz",  # the override VEVENT is untouched
    ):
        assert kept in out, kept


def test_patch_targets_master_not_override() -> None:
    # The override VEVENT shares the UID — the master (no RECURRENCE-ID) must be patched even
    # though the override appears later in the document.
    out = patch_vevent(_FOREIGN, uid="remote-1", changes={"SUMMARY": "SUMMARY:Neu"})
    master_part, override_part = out.split("RECURRENCE-ID", 1)
    assert "SUMMARY:Neu" in master_part
    assert "SUMMARY:Verschobene Instanz" in override_part


def test_patch_never_touches_nested_component_properties() -> None:
    # DESCRIPTION exists only inside the VALARM — a VEVENT-level change must INSERT a new
    # property line, not overwrite the alarm's.
    out = patch_vevent(
        _FOREIGN, uid="remote-1", changes={"DESCRIPTION": "DESCRIPTION:Neue Beschreibung"}
    )
    assert "DESCRIPTION:Neue Beschreibung" in out
    assert "DESCRIPTION:Erinnerung" in out  # the alarm's own description survives


def test_patch_inserts_missing_and_removes_properties() -> None:
    out = patch_vevent(
        _FOREIGN,
        uid="remote-1",
        changes={"TRANSP": "TRANSP:TRANSPARENT", "SUMMARY": None},
    )
    assert "TRANSP:TRANSPARENT" in out
    assert "SUMMARY:Alter Titel" not in out
    assert "SUMMARY:Verschobene Instanz" in out  # removal is scoped to the master block


def test_patch_replaces_folded_property_as_a_whole() -> None:
    out = patch_vevent(_FOREIGN, uid="remote-1", changes={"X-CUSTOM-PROP": "X-CUSTOM-PROP:kurz"})
    assert "X-CUSTOM-PROP:kurz\r\n" in out
    assert "ange-gefaltete-zeile" not in out  # the continuation line went with its property


def test_patch_collapses_multiple_lines_of_same_property() -> None:
    doc = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:u1\r\nRRULE:FREQ=WEEKLY\r\n"
        "EXDATE:20260808T090000Z\r\nEXDATE:20260815T090000Z\r\n"
        "END:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    out = patch_vevent(doc, uid="u1", changes={"EXDATE": "EXDATE:20260822T090000Z"})
    assert out.count("EXDATE") == 1
    assert "EXDATE:20260822T090000Z" in out


def test_patch_unknown_uid_raises() -> None:
    with pytest.raises(VeventNotFoundError):
        patch_vevent(_FOREIGN, uid="nope", changes={"SUMMARY": "SUMMARY:X"})


def test_patch_is_idempotent_and_normalises_bare_lf() -> None:
    changes = {"SUMMARY": "SUMMARY:Neu"}
    once = patch_vevent(_FOREIGN, uid="remote-1", changes=changes)
    twice = patch_vevent(once, uid="remote-1", changes=changes)
    assert once == twice
    bare_lf = _FOREIGN.replace("\r\n", "\n")
    assert patch_vevent(bare_lf, uid="remote-1", changes=changes) == once


# --- build_patch_changes ------------------------------------------------------


def test_changes_only_for_changed_fields() -> None:
    eff = {"title": "Neu", "busy": False}
    changes = build_patch_changes(changed={"title"}, eff=eff, tzid="UTC")
    assert set(changes) == {"SUMMARY"}


def test_time_change_rewrites_both_stamps_in_tzid_form() -> None:
    eff = {"starts_at": _T0, "ends_at": _T1, "all_day": False}
    changes = build_patch_changes(changed={"starts_at"}, eff=eff, tzid="Europe/Vienna")
    local = _T0.astimezone(ZoneInfo("Europe/Vienna")).strftime("%Y%m%dT%H%M%S")
    assert changes["DTSTART"] == f"DTSTART;TZID=Europe/Vienna:{local}"
    assert changes["DTEND"].startswith("DTEND;TZID=Europe/Vienna:")


def test_all_day_change_uses_value_date() -> None:
    eff = {"starts_at": _T0, "ends_at": datetime(2026, 8, 2, tzinfo=UTC), "all_day": True}
    changes = build_patch_changes(changed={"all_day"}, eff=eff, tzid="UTC")
    assert changes["DTSTART"] == "DTSTART;VALUE=DATE:20260801"
    assert changes["DTEND"] == "DTEND;VALUE=DATE:20260802"


def test_rrule_clear_drops_exdates_and_busy_maps_to_transp() -> None:
    changes = build_patch_changes(
        changed={"rrule", "busy"}, eff={"rrule": None, "busy": True}, tzid="UTC"
    )
    assert changes["RRULE"] is None
    assert changes["EXDATE"] is None
    assert changes["TRANSP"] == "TRANSP:OPAQUE"
