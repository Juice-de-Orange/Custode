"""CalDAV client adapter (P9-S3/S4, ADR-0079/0080). Reads a collection with exactly one
``REPORT calendar-query`` (Depth: 1, VEVENT filter, ``getetag`` + ``calendar-data``) and writes
single resources back via GET/PUT/DELETE (write-back, 9-S4).

The URL is user-supplied, so every request runs through ``kernel/fetch.safe_request`` (SSRF
guard, credential redirects locked to the origin, size caps). hrefs come from the server and
are only ever accepted as server-absolute PATHS — an absolute-URL href would let a malicious
server redirect our credential (Basic or Bearer) to a foreign origin via ``urljoin``. The 207
multistatus body is untrusted XML from a user-configured server -> parsed with ``defusedxml``
(XXE/entity-bomb protection). Errors RAISE ``CaldavError`` with a category slug — never ``[]``
(the sync's deletion diff would mass-tombstone) and never a URL/credential/content detail in the
message or log (attacker-influenced)."""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx
from defusedxml.ElementTree import fromstring as defused_fromstring

from app.kernel.fetch import (
    FetchBlockedError,
    FetchError,
    FetchTooLargeError,
    safe_request,
)
from app.kernel.ports.caldav import CaldavAuth, CaldavError, CaldavObject
from app.logging import get_logger
from app.settings import Settings

_log = get_logger("adapters.caldav")

_USER_AGENT = "CustodeCalendarSync/1.0"
# CalDAV responses carry every event of the collection — 10 MiB is generous for a household
# calendar and still bounds a hostile server (the 2-MiB recipe cap stays untouched).
_MAX_BYTES = 10 * 1024 * 1024

_DAV = "{DAV:}"
_CAL = "{urn:ietf:params:xml:ns:caldav}"

_REPORT_BODY = (
    b'<?xml version="1.0" encoding="utf-8"?>'
    b'<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
    b"<d:prop><d:getetag/><c:calendar-data/></d:prop>"
    b'<c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT"/></c:comp-filter>'
    b"</c:filter></c:calendar-query>"
)


def parse_multistatus(xml_text: str) -> list[CaldavObject]:
    """Pure: extract ``(href, etag, calendar-data)`` from a 207 multistatus document. Entries
    without a 2xx propstat or without calendar-data are skipped (e.g. 404 propstats). Raises
    ``CaldavError("invalid_response")`` on malformed/hostile XML."""
    try:
        root = defused_fromstring(xml_text)
    except Exception as exc:  # ParseError, EntitiesForbidden, DTDForbidden, …
        raise CaldavError("invalid_response") from exc

    objects: list[CaldavObject] = []
    for response in root.iter(f"{_DAV}response"):
        href_el = response.find(f"{_DAV}href")
        href = (href_el.text or "").strip() if href_el is not None else ""
        if not href:
            continue
        ics_text: str | None = None
        etag: str | None = None
        for propstat in response.findall(f"{_DAV}propstat"):
            status_el = propstat.find(f"{_DAV}status")
            status_text = (status_el.text or "") if status_el is not None else ""
            if " 200 " not in f"{status_text} ":
                continue  # only the 2xx propstat carries usable props
            prop = propstat.find(f"{_DAV}prop")
            if prop is None:
                continue
            data_el = prop.find(f"{_CAL}calendar-data")
            if data_el is not None and data_el.text and data_el.text.strip():
                ics_text = data_el.text
            etag_el = prop.find(f"{_DAV}getetag")
            if etag_el is not None and etag_el.text:
                etag = etag_el.text.strip()
        if ics_text is not None:
            objects.append(CaldavObject(href=href, etag=etag, ics_text=ics_text))
    return objects


def _target(url: str, href: str) -> str:
    """Resolve a server-provided href against the subscription URL — PATHS ONLY. An href with a
    scheme or netloc would make ``urljoin`` swap the whole origin and carry our credential — Basic
    or Bearer — to a foreign host (credential exfiltration via hostile REPORT responses)."""
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        raise CaldavError("invalid_response")
    return urljoin(url, href)


class CaldavClient:
    def __init__(self, settings: Settings) -> None:
        self._allow_private = settings.caldav_allow_private_urls
        self._timeout = httpx.Timeout(settings.caldav_timeout_s, connect=5.0)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        auth: CaldavAuth,
    ) -> tuple[int, str, dict[str, str]]:
        """One guarded request with the shared FetchError -> CaldavError mapping.

        Both credential forms go to the fetch layer as credentials, so its redirect origin-lock
        applies to a Bearer token exactly as it does to Basic auth."""
        try:
            return await safe_request(
                method,
                url,
                headers=headers,
                content=content,
                auth=auth.basic,
                bearer=auth.bearer,
                max_bytes=_MAX_BYTES,
                allow_private=self._allow_private,
                user_agent=_USER_AGENT,
                http_timeout=self._timeout,
            )
        except FetchBlockedError as exc:
            raise CaldavError("blocked_url") from exc
        except FetchTooLargeError as exc:
            raise CaldavError("too_large") from exc
        except FetchError as exc:  # failed / too many redirects
            raise CaldavError("unreachable") from exc

    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[CaldavObject]:
        status, body, _headers = await self._send(
            "REPORT",
            url,
            headers={"Depth": "1", "Content-Type": "application/xml; charset=utf-8"},
            content=_REPORT_BODY,
            auth=auth,
        )
        if status in (401, 403, 407):
            raise CaldavError("auth_failed")
        if status in (400, 404, 405, 501):
            # The server answered but refuses the REPORT — not a calendar collection URL.
            raise CaldavError("not_calendar")
        if status not in (200, 207):  # 207 is the spec answer; accept a lenient plain 200
            raise CaldavError("unreachable")

        objects = parse_multistatus(body)
        # Aggregate count only — never the URL or any event content.
        _log.debug("caldav_report_ok", objects=len(objects))
        return objects

    async def get_object(self, *, url: str, href: str, auth: CaldavAuth) -> CaldavObject:
        status, body, headers = await self._send(
            "GET",
            _target(url, href),
            headers={"Accept": "text/calendar"},
            auth=auth,
        )
        if status in (401, 403, 407):
            raise CaldavError("auth_failed")
        if status in (404, 410):
            raise CaldavError("not_found")
        if status != 200:
            raise CaldavError("unreachable")
        return CaldavObject(href=href, etag=headers.get("etag"), ics_text=body)

    async def put_object(
        self,
        *,
        url: str,
        href: str,
        ics_text: str,
        etag: str | None,
        if_none_match: bool,
        auth: CaldavAuth,
    ) -> str | None:
        headers = {"Content-Type": "text/calendar; charset=utf-8"}
        if etag is not None:
            headers["If-Match"] = etag
        if if_none_match:
            headers["If-None-Match"] = "*"
        status, _body, resp_headers = await self._send(
            "PUT",
            _target(url, href),
            headers=headers,
            content=ics_text.encode("utf-8"),
            auth=auth,
        )
        if status in (401, 403, 407):
            raise CaldavError("auth_failed")
        if status in (409, 412):
            raise CaldavError("conflict")
        if status in (404, 410):
            raise CaldavError("not_found")
        if status == 413:
            raise CaldavError("too_large")
        if status not in (200, 201, 204):
            raise CaldavError("unreachable")
        _log.debug("caldav_put_ok")
        return resp_headers.get("etag")

    async def delete_object(
        self, *, url: str, href: str, etag: str | None, auth: CaldavAuth
    ) -> None:
        headers = {"If-Match": etag} if etag is not None else None
        status, _body, _headers = await self._send(
            "DELETE", _target(url, href), headers=headers, auth=auth
        )
        if status in (401, 403, 407):
            raise CaldavError("auth_failed")
        if status in (409, 412):
            raise CaldavError("conflict")
        if status in (404, 410):
            # Honest category — the SERVICE decides that "already gone" counts as success.
            raise CaldavError("not_found")
        if status not in (200, 204):
            raise CaldavError("unreachable")
        _log.debug("caldav_delete_ok")
