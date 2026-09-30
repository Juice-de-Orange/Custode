from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class CalendarEvent(HouseholdScoped, Base):
    """A calendar event (KONZEPT §5.11). RLS: household_id (tenant isolation). ``version`` (mixin,
    trigger-bumped) is the ETag for PATCH + If-Match (ADR-0034).

    ``layer`` splits visibility: ``household`` events are seen by every member, ``personal`` events
    only by their ``owner_id`` (enforced query-side, ADR-0040). ``busy`` marks the event as a
    blocking commitment — the later scheduling engine reads it as a „belegt"-signal. ``all_day``
    events ignore the time component. ``ends_at >= starts_at`` is a CHECK in the migration."""

    __tablename__ = "calendar_events"

    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)  # creator user_id
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # household | personal (CHECK constraint in migration).
    layer: Mapped[str] = mapped_column(String(10), server_default=text("'household'"))
    busy: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    # normal | absence | guest (CHECK constraint in migration, P5-S4). ``absence`` (KONZEPT §5.11)
    # marks a member as away — the seam the scheduling/fairness logic reads via calendar.api;
    # ``guest`` flags a visitor. Plain events are ``normal``.
    kind: Mapped[str] = mapped_column(String(10), server_default=text("'normal'"))
    # RFC-5545 recurrence rule (e.g. "FREQ=WEEKLY;BYDAY=MO"); NULL for a one-off. The stored
    # starts_at/ends_at are the first occurrence + duration; occurrences are expanded on read
    # (calendar/expand.py, ADR-0041). Editing/deleting affects the whole series.
    rrule: Mapped[str | None] = mapped_column(Text)
    # RFC-5545 EXDATE: the original start instants of cancelled single occurrences of this series
    # (P5-S5). expand.py skips occurrences whose start matches one; the ICS feed emits them as
    # EXDATE so subscribers drop them too. Set semantics (cancel = add, restore = remove).
    exdates: Mapped[list[datetime]] = mapped_column(
        ARRAY(DateTime(timezone=True)), server_default=text("'{}'")
    )
    # UID of the VEVENT this event was imported from (ICS import, P5-S6); NULL for events created in
    # the app. Lets a re-import of the same .ics dedupe within the household (idempotent).
    source_uid: Mapped[str | None] = mapped_column(Text)
    # IANA time zone the series is anchored in (P5-S9, ADR-0047). A recurring event is expanded in
    # this zone so its wall-clock time is stable across DST; "UTC" reproduces the pre-S9 behaviour.
    tzid: Mapped[str] = mapped_column(String(64), server_default=text("'UTC'"))
    # Moved single occurrences (P5-S10, ADR-0048): {original_start_iso: {starts_at, ends_at}}. On
    # expansion the override replaces the rule-generated occurrence at that key (RECURRENCE-ID idea,
    # kept compact in the master row instead of a separate override event).
    overrides: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    # Mirror provenance (P9-S3, ADR-0079): set = this row mirrors a VEVENT of that external CalDAV
    # subscription (``source_uid`` = its UID); NULL = local/ICS-import (unchanged behaviour).
    # FK ON DELETE CASCADE backstops the retention reaper.
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Write-back anchors (P9-S4, ADR-0080, mirror rows only): the server-absolute resource path
    # (GET/PUT/DELETE target) and the last known server ETag (If-Match on DELETE; NULL = next
    # write unconditional). The pull-sync stamps both on EVERY run.
    ext_href: Mapped[str | None] = mapped_column(Text)
    ext_etag: Mapped[str | None] = mapped_column(Text)


class ExternalCalendarSubscription(HouseholdScoped, Base):
    """A member's subscription to an external CalDAV collection (KONZEPT §10, P9-S2). RLS isolates
    the household; every read additionally filters ``member_id`` — subscriptions are personal
    (foreign URLs + credentials), so a co-member (or admin) never sees them (404 like a foreign
    ``personal`` event, ADR-0040 idea).

    ``creds_enc`` holds exactly one SecretBox value (``v1:<fernet>``, ADR-0077) over the JSON
    ``{username, password}`` — the username is PII and stays inside the ciphertext; NULL means
    anonymous access (public collections). Plaintext exists only in process memory, never in a
    response, log, or event payload. ``enabled`` pauses syncing without deleting; ``last_sync_at``
    stays NULL in 9-S2 and is stamped by the 9-S3 pull-sync cron."""

    __tablename__ = "external_calendar_subscriptions"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    label: Mapped[str] = mapped_column(String(100))
    caldav_url: Mapped[str] = mapped_column(String(2000))
    creds_enc: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Last failure category slug (``unreachable``, ``auth_failed``, …, P9-S3) — never a URL or
    # content; NULL = the last sync run succeeded. ``last_sync_at`` = last SUCCESSFUL sync.
    last_sync_error: Mapped[str | None] = mapped_column(String(200))


class CalendarFeed(HouseholdScoped, Base):
    """A member's secret ICS subscription feed (KONZEPT §5.11, ADR-0042). One per member. ``token``
    is a high-entropy URL secret: ``GET /v1/calendar/feed/<token>.ics`` returns that member's
    visible events as iCalendar — unauthenticated (calendar apps can't send cookies). RLS isolates
    the household for the owner's CRUD; a ``maint_all`` policy lets the feed endpoint resolve the
    token across households (like the auth token lookup). Revocable (rotate/delete)."""

    __tablename__ = "calendar_feeds"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
