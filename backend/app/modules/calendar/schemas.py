"""HTTP request/response contracts for ``calendar`` (single source for the OpenAPI schema -> web zod
client). Separate from the ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

EventLayer = Literal["household", "personal"]
EventKind = Literal["normal", "absence", "guest"]


class EventCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=200)
    starts_at: datetime
    ends_at: datetime
    all_day: bool = False
    layer: EventLayer = "household"
    busy: bool = True
    kind: EventKind = "normal"
    # RFC-5545 RRULE (e.g. "FREQ=WEEKLY;BYDAY=MO"); null = one-off. Validated on create.
    rrule: str | None = Field(default=None, max_length=500)
    # IANA time zone the series is anchored in (DST-correctness, P5-S9). Validated on create.
    tzid: str = Field(default="UTC", max_length=64)
    # Target subscription (P9-S4, ADR-0080): set = the event is created synchronously in the
    # external CalDAV calendar and kept as a mirror. Forces layer='personal'; requires
    # kind='normal' and tzid='UTC' (non-round-trippable fields answer 422).
    subscription_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _end_after_start(self) -> EventCreate:
        if self.ends_at < self.starts_at:
            raise ValueError("ends_at must not be before starts_at")
        return self


class EventUpdate(BaseModel):
    """All fields optional (partial update under If-Match). A null field is left unchanged."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    location: str | None = Field(default=None, max_length=200)
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    all_day: bool | None = None
    layer: EventLayer | None = None
    busy: bool | None = None
    kind: EventKind | None = None
    rrule: str | None = Field(default=None, max_length=500)
    tzid: str | None = Field(default=None, max_length=64)


class OccurrenceRef(BaseModel):
    """Identifies one occurrence of a series by its original start instant (RFC-5545 EXDATE key)."""

    occurrence_start: datetime


class OccurrenceMove(BaseModel):
    """Move one occurrence (identified by ``occurrence_start``) to a new time (P5-S10)."""

    occurrence_start: datetime
    new_start: datetime
    new_end: datetime

    @model_validator(mode="after")
    def _end_after_start(self) -> OccurrenceMove:
        if self.new_end < self.new_start:
            raise ValueError("new_end must not be before new_start")
        return self


class EventResponse(BaseModel):
    """One event or one expanded occurrence. For a recurring series, ``id``/``series_id`` are the
    master id and ``starts_at``/``ends_at`` are the concrete occurrence; ``recurring`` is true and
    ``rrule`` carries the series rule. Editing/deleting by ``id`` affects the whole series;
    ``exdates`` are the cancelled single occurrences (P5-S5)."""

    id: uuid.UUID
    series_id: uuid.UUID
    owner_id: uuid.UUID
    title: str
    description: str | None
    location: str | None
    starts_at: datetime
    ends_at: datetime
    # The rule-generated start of this occurrence (the cancel/move key); null for the master row and
    # one-offs. ``starts_at`` may differ if the occurrence was moved (P5-S10).
    original_start: datetime | None
    all_day: bool
    layer: EventLayer
    busy: bool
    kind: EventKind
    rrule: str | None
    recurring: bool
    exdates: list[datetime]
    tzid: str
    # True = mirror of an external CalDAV subscription (P9-S3): read-only until write-back
    # (9-S4) — the UI renders it as its own layer/badge and suppresses edit controls.
    external: bool = False


def _validate_caldav_url(value: str) -> str:
    """Shape-only validation at save time (P9-S2): http(s), a host, and no userinfo — credentials
    belong in the encrypted fields, never in the plaintext URL column. Deliberately NO private-IP/
    SSRF check here: a DNS check at save time is TOCTOU-unsafe (rebinding); the fetch-time guard
    (``kernel/fetch``-style pinning) is applied by the 9-S3 pull-sync when it actually connects."""
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"}:
        raise ValueError("caldav_url must be http(s)")
    if not parts.hostname:
        raise ValueError("caldav_url must have a host")
    if parts.username is not None or parts.password is not None:
        raise ValueError("caldav_url must not embed credentials")
    return value


class SubscriptionCreate(BaseModel):
    """Subscribe to an external CalDAV collection (P9-S2). ``username``/``password`` are optional
    (public collections work anonymously) but only valid together — they are encrypted server-side
    (ADR-0077) and never returned."""

    label: str = Field(min_length=1, max_length=100)
    caldav_url: str = Field(min_length=1, max_length=2000)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    enabled: bool = True

    @field_validator("caldav_url")
    @classmethod
    def _url_shape(cls, value: str) -> str:
        return _validate_caldav_url(value)

    @model_validator(mode="after")
    def _credentials_pair(self) -> SubscriptionCreate:
        if (self.username is None) != (self.password is None):
            raise ValueError("username and password are only valid together")
        return self


class SubscriptionUpdate(BaseModel):
    """Partial update under If-Match. A null field is left unchanged; ``username``+``password``
    together replace the stored credentials; ``clear_credentials`` drops them (422 combined with
    new credentials)."""

    label: str | None = Field(default=None, min_length=1, max_length=100)
    caldav_url: str | None = Field(default=None, min_length=1, max_length=2000)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    enabled: bool | None = None
    clear_credentials: bool = False

    @field_validator("caldav_url")
    @classmethod
    def _url_shape(cls, value: str | None) -> str | None:
        return None if value is None else _validate_caldav_url(value)

    @model_validator(mode="after")
    def _credentials_consistent(self) -> SubscriptionUpdate:
        if (self.username is None) != (self.password is None):
            raise ValueError("username and password are only valid together")
        if self.clear_credentials and self.username is not None:
            raise ValueError("clear_credentials excludes new credentials")
        return self


class SubscriptionResponse(BaseModel):
    """One CalDAV subscription — write-only credentials: the wire shape carries only
    ``has_credentials``, never username/password/ciphertext. ``last_sync_at`` stays null until the
    9-S3 pull-sync stamps it."""

    id: uuid.UUID
    member_id: uuid.UUID
    label: str
    caldav_url: str
    enabled: bool
    has_credentials: bool
    last_sync_at: datetime | None
    # Category slug of the last failed sync run (``unreachable``, ``auth_failed``, …, P9-S3);
    # null = the last run succeeded. ``last_sync_at`` is the last SUCCESSFUL sync.
    last_sync_error: str | None = None


class SubscriptionCheckResponse(BaseModel):
    """Outcome of a connection probe (P9). ``category`` reuses the ``last_sync_error`` slug family
    so the web renders it with the same message map; ``objects`` is a plain count (never titles or
    content) so a successful check can say "reachable, 42 entries" without leaking a calendar."""

    ok: bool
    category: str | None = None
    objects: int | None = None


class FeedResponse(BaseModel):
    """The caller's secret ICS subscription URL (paste into Google/Nextcloud/Apple Calendar)."""

    url: str


class IcsImportRequest(BaseModel):
    """Raw iCalendar text to import (uploaded file content — no URL fetch, so no SSRF). Imported
    events land in ``layer`` and are owned by the caller. ``content`` is size-capped."""

    content: str = Field(min_length=1, max_length=1_000_000)
    layer: EventLayer = "household"


class IcsImportResult(BaseModel):
    """Outcome of an import: how many VEVENTs were created, skipped as already-imported duplicates
    (same UID in the household), or failed (e.g. an invalid RRULE)."""

    imported: int
    skipped: int
    failed: int
