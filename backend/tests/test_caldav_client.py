"""Unit tests for the CalDAV multistatus parsing (P9-S3, ADR-0079) — pure, no network, no
Docker. The XML comes from user-configured servers (untrusted), so hostile documents must fail
opaquely (defusedxml) instead of expanding entities."""

from __future__ import annotations

import pytest

from app.adapters.caldav.client import parse_multistatus
from app.kernel.ports.caldav import CaldavError

_ICS_1 = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:a\r\nEND:VEVENT\r\nEND:VCALENDAR"
_ICS_2 = "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:b\r\nEND:VEVENT\r\nEND:VCALENDAR"


def _multistatus(*responses: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
        + "".join(responses)
        + "</d:multistatus>"
    )


def _response(href: str, ics: str, *, etag: str | None = '"v1"') -> str:
    etag_el = f"<d:getetag>{etag}</d:getetag>" if etag else ""
    return (
        f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>"
        f"{etag_el}<c:calendar-data>{ics}</c:calendar-data>"
        "</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
    )


def test_parses_objects_with_etag_and_data() -> None:
    xml = _multistatus(
        _response("/dav/cal/a.ics", _ICS_1),
        _response("/dav/cal/b.ics", _ICS_2, etag=None),
    )
    objects = parse_multistatus(xml)
    assert [o.href for o in objects] == ["/dav/cal/a.ics", "/dav/cal/b.ics"]
    assert objects[0].etag == '"v1"'
    assert objects[1].etag is None
    assert "UID:a" in objects[0].ics_text
    assert "UID:b" in objects[1].ics_text


def test_skips_non_200_propstats_and_dataless_entries() -> None:
    xml = _multistatus(
        # A 404 propstat (property not found) must not yield an object.
        "<d:response><d:href>/dav/cal/x.ics</d:href><d:propstat><d:prop>"
        "<c:calendar-data/></d:prop>"
        "<d:status>HTTP/1.1 404 Not Found</d:status></d:propstat></d:response>",
        # A 200 propstat without calendar-data (e.g. only an etag) is skipped too.
        "<d:response><d:href>/dav/cal/y.ics</d:href><d:propstat><d:prop>"
        '<d:getetag>"e"</d:getetag></d:prop>'
        "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>",
        _response("/dav/cal/ok.ics", _ICS_1),
    )
    objects = parse_multistatus(xml)
    assert [o.href for o in objects] == ["/dav/cal/ok.ics"]


def test_empty_multistatus_is_empty_collection() -> None:
    assert parse_multistatus(_multistatus()) == []


def test_malformed_xml_raises_invalid_response() -> None:
    with pytest.raises(CaldavError) as exc:
        parse_multistatus("<d:multistatus xmlns:d='DAV:'><unclosed>")
    assert exc.value.category == "invalid_response"


def test_entity_expansion_attack_raises_invalid_response() -> None:
    # Billion-laughs style document: defusedxml must refuse it (stdlib ElementTree would expand).
    bomb = (
        '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        '<d:multistatus xmlns:d="DAV:"><d:response><d:href>&lol2;</d:href>'
        "</d:response></d:multistatus>"
    )
    with pytest.raises(CaldavError) as exc:
        parse_multistatus(bomb)
    assert exc.value.category == "invalid_response"


def test_external_entity_attack_raises_invalid_response() -> None:
    xxe = (
        '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        '<d:multistatus xmlns:d="DAV:"><d:response><d:href>&x;</d:href>'
        "</d:response></d:multistatus>"
    )
    with pytest.raises(CaldavError) as exc:
        parse_multistatus(xxe)
    assert exc.value.category == "invalid_response"


def test_target_rejects_absolute_and_protocol_relative_hrefs() -> None:
    # A hostile server could send an absolute href; urljoin would swap the origin and carry our
    # Basic auth to a foreign host (credential exfiltration). Must fail BEFORE any request.
    from app.adapters.caldav.client import _target

    assert _target("http://cal.example/dav/", "/dav/x.ics") == "http://cal.example/dav/x.ics"
    assert _target("http://cal.example/dav/", "x.ics") == "http://cal.example/dav/x.ics"
    for hostile in ("http://evil.example/x.ics", "//evil.example/x.ics", "https://evil/x"):
        with pytest.raises(CaldavError) as exc:
            _target("http://cal.example/dav/", hostile)
        assert exc.value.category == "invalid_response"
