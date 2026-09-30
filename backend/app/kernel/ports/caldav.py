"""CalDAV port (P9-S3/S4, ADR-0079/0080): read one external collection and write single
resources back.

The adapter exchanges RAW iCalendar text per resource — parsing/patching happens module-side
(``modules/calendar``), because adapters must not import modules (import-linter).

Error contract: implementations RAISE ``CaldavError`` on any fetch/protocol failure — an empty
``list_objects`` result strictly means "the collection is empty". The pull-sync's deletion diff
tombstones every mirrored event that is absent from the result, so a network hiccup silently
returning ``[]`` would mass-delete a household's mirrored calendar."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request
from pydantic import BaseModel


class CaldavObject(BaseModel):
    """One calendar resource from a REPORT/GET response."""

    href: str  # server-relative resource path (unique per object)
    etag: str | None  # server ETag if provided (If-Match anchor for write-back, 9-S4)
    ics_text: str  # raw iCalendar document (VCALENDAR with >= 1 VEVENT)


@dataclass(frozen=True)
class CaldavAuth:
    """How to authenticate against a collection: Basic (Nextcloud/iCloud) or Bearer (Google).

    One value object instead of parallel ``username``/``password``/``bearer`` parameters on every
    method: the forms are mutually exclusive, and three optionals side by side would leave "what
    if two are set?" to each call site. ``ANONYMOUS`` is the public-collection case.

    Both forms are equally credential: ``kernel/fetch`` origin-locks redirects for either, because
    a Bearer token is pure inhaber authority with no origin binding of its own."""

    username: str | None = None
    password: str | None = None
    bearer: str | None = None

    @property
    def basic(self) -> tuple[str, str] | None:
        """The Basic pair for the fetch layer, or ``None`` (anonymous or Bearer)."""
        if self.username is None or self.password is None:
            return None
        return (self.username, self.password)


ANONYMOUS = CaldavAuth()


class CaldavError(Exception):
    """Fetch/protocol failure. ``category`` is a short slug (``unreachable``, ``auth_failed``,
    ``not_calendar``, ``invalid_response``, ``too_large``, ``blocked_url``, ``conflict`` =
    remote precondition/412, ``not_found`` = href answered 404/410, ``sync_disabled`` = Null
    adapter) — never a URL, credential, or response content (all attacker-influenced)."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


class CaldavPort(Protocol):
    async def list_objects(self, *, url: str, auth: CaldavAuth) -> list[CaldavObject]: ...

    async def get_object(self, *, url: str, href: str, auth: CaldavAuth) -> CaldavObject: ...

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
        """PUT one resource. ``etag`` set -> ``If-Match`` (edit); ``if_none_match`` ->
        ``If-None-Match: *`` (create must not overwrite). Returns the new ETag when the server
        provides one, else None (caller refreshes or leaves NULL)."""
        ...

    async def delete_object(
        self, *, url: str, href: str, etag: str | None, auth: CaldavAuth
    ) -> None:
        """DELETE one resource (``If-Match`` when ``etag`` is given; unconditional otherwise)."""
        ...


def get_caldav(request: Request) -> CaldavPort:
    """FastAPI dependency: the CalDAV adapter composed at startup (``app.state.caldav``) — the
    ``get_mail`` pattern: kernel-side so modules depend only on ``kernel/*``; the concrete
    adapter is selected in the composition root (``main.py``)."""
    caldav: CaldavPort = request.app.state.caldav
    return caldav
