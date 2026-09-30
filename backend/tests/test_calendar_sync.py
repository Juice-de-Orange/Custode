"""Unit tests for the pure parts of the CalDAV pull-sync (P9-S3, ADR-0079) — no DB, no Docker:
``_build_wanted`` (which VEVENTs are mirror-worthy) and ``_differs`` (the update decision)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.kernel.ports.caldav import CaldavObject
from app.modules.calendar.sync import _build_wanted, _differs, _mirror_fields


def _obj(*vevents: str) -> CaldavObject:
    body = "\r\n".join(vevents)
    ics = f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n{body}\r\nEND:VCALENDAR\r\n"
    return CaldavObject(href="/cal/x.ics", etag=None, ics_text=ics)


def _vevent(uid: str, *extra: str) -> str:
    lines = [f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:E-{uid}\r\nDTSTART:20260701T090000Z"]
    lines.extend(extra)
    lines.append("END:VEVENT")
    return "\r\n".join(lines)


def test_wanted_keys_by_uid_and_skips_uidless() -> None:
    wanted = _build_wanted(
        [
            _obj(_vevent("a")),
            _obj("BEGIN:VEVENT\r\nSUMMARY:NoUid\r\nDTSTART:20260701T090000Z\r\nEND:VEVENT"),
        ]
    )
    assert set(wanted) == {"a"}


def test_wanted_ignores_recurrence_id_overrides() -> None:
    # Master + moved single occurrence share the UID — the master must win (documented gap:
    # overrides are not mirrored; naive dedup would drop or double the series).
    wanted = _build_wanted(
        [
            _obj(
                _vevent("s1", "RRULE:FREQ=WEEKLY"),
                _vevent("s1", "RECURRENCE-ID:20260708T090000Z"),
            )
        ]
    )
    assert set(wanted) == {"s1"}
    assert wanted["s1"].ev.rrule == "FREQ=WEEKLY"


def test_wanted_drops_cancelled_uids_entirely() -> None:
    wanted = _build_wanted([_obj(_vevent("c1", "STATUS:CANCELLED"), _vevent("ok"))])
    assert set(wanted) == {"ok"}


def test_wanted_skips_invalid_rrule_and_inverted_range() -> None:
    wanted = _build_wanted(
        [
            _obj(_vevent("bad-rule", "RRULE:FREQ=NOPE")),
            _obj(_vevent("inverted", "DTEND:20260701T080000Z")),
            _obj(_vevent("ok")),
        ]
    )
    assert set(wanted) == {"ok"}


def test_wanted_first_wins_on_feed_internal_duplicates() -> None:
    wanted = _build_wanted([_obj(_vevent("dup"), _vevent("dup", "LOCATION:Zweitfassung"))])
    assert wanted["dup"].ev.location is None


def test_differs_detects_field_and_exdate_changes() -> None:
    [w] = _build_wanted([_obj(_vevent("d1", "EXDATE:20260708T090000Z"))]).values()
    ev = w.ev
    fields = _mirror_fields(ev)
    row = SimpleNamespace(**fields)
    assert _differs(row, fields) is False  # type: ignore[arg-type] — duck-typed row

    renamed = dict(fields, title="Anders")
    assert _differs(row, renamed) is True  # type: ignore[arg-type]

    # Same instant, different representation: exdates compare as UTC-instant sets.
    from zoneinfo import ZoneInfo

    same_instant = dict(
        fields, exdates=[datetime(2026, 7, 8, 11, 0, tzinfo=ZoneInfo("Europe/Vienna"))]
    )
    assert _differs(row, same_instant) is False  # type: ignore[arg-type]

    moved = dict(fields, exdates=[datetime(2026, 7, 15, 9, 0, tzinfo=UTC)])
    assert _differs(row, moved) is True  # type: ignore[arg-type]


def test_mirror_fields_caps_lengths_and_maps_busy() -> None:
    [w] = _build_wanted(
        [
            _obj(
                "BEGIN:VEVENT\r\nUID:long\r\nSUMMARY:"
                + "x" * 300
                + "\r\nDTSTART:20260701T090000Z\r\nLOCATION:"
                + "y" * 300
                + "\r\nTRANSP:TRANSPARENT\r\nEND:VEVENT"
            )
        ]
    ).values()
    ev = w.ev
    fields = _mirror_fields(ev)
    title = fields["title"]
    location = fields["location"]
    assert isinstance(title, str) and len(title) == 200
    assert isinstance(location, str) and len(location) == 200
    assert fields["busy"] is False  # TRANSP:TRANSPARENT does not block scheduling (S-16)
    assert fields["tzid"] == "UTC"
