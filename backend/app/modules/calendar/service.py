"""calendar use-cases (KONZEPT §5.11). Services run on the request's RLS-scoped session; the
dependency commits the unit of work.

Layer visibility (ADR-0040): RLS isolates the household (tenant); within it, ``personal`` events are
visible only to their ``owner_id`` — enforced query-side here, not by RLS. Write path = PATCH +
If-Match (``expected_version`` = ETag; 412 on stale)."""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from urllib.parse import urlsplit

from sqlalchemy import CursorResult, Select, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.crypto import SecretBoxError, get_secretbox, require_secretbox
from app.kernel.events.emit import emit
from app.kernel.http.problem import ProblemException
from app.kernel.ports.caldav import ANONYMOUS, CaldavAuth, CaldavError, CaldavPort
from app.modules.calendar import ics_write
from app.modules.calendar.creds import decode_credentials, encode_credentials
from app.modules.calendar.expand import (
    as_utc_instant,
    expand_occurrences,
    is_occurrence,
    is_valid_rrule,
    is_valid_tzid,
    occurrence_key,
)
from app.modules.calendar.ics_parse import parse_ics
from app.modules.calendar.models import (
    CalendarEvent,
    CalendarFeed,
    ExternalCalendarSubscription,
)
from app.modules.calendar.schemas import (
    EventCreate,
    EventUpdate,
    SubscriptionCreate,
    SubscriptionUpdate,
)

# Default horizon for expanding recurring series when the caller gives no upper bound.
_DEFAULT_HORIZON = timedelta(days=90)

# (event, original_start, occurrence_start, occurrence_end) — one row per concrete occurrence in the
# window. ``original_start`` is the rule instant (cancel/move key); the rest are the effective time.
Occurrence = tuple[CalendarEvent, datetime, datetime, datetime]


def _visible(
    stmt: Select[tuple[CalendarEvent]], *, viewer_id: uuid.UUID
) -> Select[tuple[CalendarEvent]]:
    """Restrict to events the viewer may see: any ``household`` event, or their own ``personal``."""
    return stmt.where(or_(CalendarEvent.layer == "household", CalendarEvent.owner_id == viewer_id))


def _overrides(event: CalendarEvent) -> dict[str, tuple[datetime, datetime]]:
    """Decode the stored ``overrides`` JSONB ({key: {starts_at, ends_at}}) into the (start, end)
    datetime tuples the pure expander consumes. Ignores malformed entries defensively."""
    out: dict[str, tuple[datetime, datetime]] = {}
    for key, value in (event.overrides or {}).items():
        try:
            out[key] = (
                datetime.fromisoformat(value["starts_at"]),
                datetime.fromisoformat(value["ends_at"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _reject_external(event: CalendarEvent) -> None:
    """Occurrence actions on mirrored CalDAV events stay read-only even after write-back
    (P9-S4, ADR-0080): RECURRENCE-ID overrides are not mirrored, so a local EXDATE/override
    would be rolled back by the next sync tick. 409: a resource state, not a permission."""
    if event.subscription_id is not None:
        raise ProblemException(
            slug="external_event_read_only",
            title="Externer Termin — nur Lesen (Quelle ist der abonnierte Kalender)",
            status=409,
        )


# --- CalDAV write-back plumbing (P9-S4, ADR-0080) -----------------------------


def _external_conflict() -> ProblemException:
    return ProblemException(
        slug="external_conflict",
        title="Extern geändert — der nächste Sync holt den Stand",
        status=409,
    )


def _map_caldav_error(exc: CaldavError) -> ProblemException:
    """Translate a port failure into the write-back problem family (E11). ``not_found`` on a
    DELETE is intercepted by the caller (already gone = success) before reaching this map."""
    if exc.category in ("conflict", "not_found"):
        return _external_conflict()
    if exc.category == "sync_disabled":
        return ProblemException(
            slug="caldav_disabled", title="CalDAV-Sync ist deaktiviert", status=503
        )
    # Category slugs are ours (never a URL/credential/content) — safe to expose for support.
    return ProblemException(
        slug="caldav_write_failed",
        title="Externer Kalender nicht erreichbar",
        status=502,
        extra={"category": exc.category},
    )


def _mirror_credentials(sub: ExternalCalendarSubscription) -> CaldavAuth:
    """Decrypt the subscription's credentials for a write-through (503 without a server key —
    the 9-S2 rule; anonymous subscriptions write without auth and let the server answer)."""
    if sub.creds_enc is None:
        return ANONYMOUS
    box = require_secretbox()  # 503 crypto_unconfigured (ADR-0077)
    try:
        username, password = decode_credentials(box, sub.creds_enc)
        return CaldavAuth(username=username, password=password)
    except SecretBoxError as exc:
        raise ProblemException(
            slug="caldav_write_failed",
            title="Externer Kalender nicht erreichbar",
            status=502,
            extra={"category": "creds_undecryptable"},
        ) from exc


async def _mirror_subscription(
    session: AsyncSession, event: CalendarEvent
) -> ExternalCalendarSubscription:
    """The subscription behind a mirror row, ready for a write-through. ``enabled=false`` is
    deliberately NOT an error — pausing stops the pull, not the calendar (E9). Missing anchors
    (9-S3-era rows) heal within one sync tick (E10)."""
    if event.ext_href is None or event.source_uid is None:
        raise ProblemException(
            slug="external_not_synced",
            title="Noch nicht synchronisiert — der nächste Sync-Lauf verknüpft den Termin",
            status=409,
        )
    sub = await session.get(ExternalCalendarSubscription, event.subscription_id)
    if sub is None or sub.deleted_at is not None:  # unsubscribe tombstones mirrors — defensive
        raise ProblemException(
            slug="external_not_synced",
            title="Abo nicht mehr vorhanden",
            status=409,
        )
    return sub


async def get_event(
    session: AsyncSession, *, viewer_id: uuid.UUID, event_id: uuid.UUID
) -> CalendarEvent:
    """Fetch one event the viewer may see (404 if missing, soft-deleted, or a foreign personal)."""
    event = await session.get(CalendarEvent, event_id)
    if event is None or event.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Termin nicht gefunden", status=404)
    if event.layer == "personal" and event.owner_id != viewer_id:
        raise ProblemException(slug="not_found", title="Termin nicht gefunden", status=404)
    return event


async def list_events(
    session: AsyncSession,
    *,
    viewer_id: uuid.UUID,
    frm: datetime | None = None,
    to: datetime | None = None,
) -> list[Occurrence]:
    """Visible events (RLS-scoped) expanded into concrete occurrences within ``[frm, to]``, soonest
    first. One-offs yield at most one occurrence; recurring series are expanded via the RRULE
    (calendar/expand.py). Without an upper bound, recurring series expand over a 90-day horizon from
    ``frm`` (or now) so an open-ended rule stays finite."""
    rows = list(
        await session.scalars(
            _visible(select(CalendarEvent), viewer_id=viewer_id).where(
                CalendarEvent.deleted_at.is_(None)
            )
        )
    )
    occurrences: list[Occurrence] = []
    for event in rows:
        window_from: datetime | None = frm
        window_to: datetime | None = to
        if event.rrule:  # an open-ended rule needs a finite window
            window_from = frm if frm is not None else datetime.now(UTC)
            window_to = to if to is not None else window_from + _DEFAULT_HORIZON
        for orig_start, occ_start, occ_end in expand_occurrences(
            event.starts_at,
            event.ends_at,
            event.rrule,
            window_from,
            window_to,
            event.exdates,
            event.tzid,
            _overrides(event),
        ):
            occurrences.append((event, orig_start, occ_start, occ_end))
    occurrences.sort(key=lambda occ: occ[2])
    return occurrences


async def create_event(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    owner_id: uuid.UUID,
    data: EventCreate,
    caldav: CaldavPort,
) -> CalendarEvent:
    """Create an event owned by the caller (recurring if ``rrule`` is set). 422 on an invalid
    RRULE. With ``subscription_id`` the event is first created in the external CalDAV calendar
    (synchronous write-through, P9-S4) and kept as a mirror. Emits ``calendar.event.created``."""
    if data.rrule is not None and not is_valid_rrule(data.rrule, dtstart=data.starts_at):
        raise ProblemException(
            slug="invalid_rrule", title="Ungültige Wiederholungsregel", status=422
        )
    if not is_valid_tzid(data.tzid):
        raise ProblemException(slug="invalid_tzid", title="Ungültige Zeitzone", status=422)
    if data.subscription_id is not None:
        return await _create_mirror_event(
            session, household_id=household_id, owner_id=owner_id, data=data, caldav=caldav
        )
    event = CalendarEvent(
        household_id=household_id,
        owner_id=owner_id,
        title=data.title,
        description=data.description,
        location=data.location,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        all_day=data.all_day,
        layer=data.layer,
        busy=data.busy,
        kind=data.kind,
        rrule=data.rrule,
        tzid=data.tzid,
    )
    session.add(event)
    await emit(session, type="calendar.event.created", household_id=household_id, payload={})
    await session.flush()
    return event


async def _create_mirror_event(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    owner_id: uuid.UUID,
    data: EventCreate,
    caldav: CaldavPort,
) -> CalendarEvent:
    """Create the event in the subscribed external calendar first (remote-first, E12), then as
    a mirror row. ``layer`` is silently forced to ``personal`` (E5); non-round-trippable fields
    answer 422 (E6) — a silent flip on the next sync tick would be worse."""
    sub = await session.get(ExternalCalendarSubscription, data.subscription_id)
    if sub is None or sub.deleted_at is not None or sub.member_id != owner_id:
        raise ProblemException(slug="not_found", title="Abo nicht gefunden", status=404)
    if data.kind != "normal":
        raise ProblemException(
            slug="external_kind_unsupported",
            title="Externe Termine unterstützen nur kind=normal",
            status=422,
        )
    if data.tzid != "UTC":
        raise ProblemException(
            slug="external_tzid_unsupported",
            title="Externe Termine werden UTC-verankert angelegt (tzid muss UTC sein)",
            status=422,
        )
    auth = _mirror_credentials(sub)

    uid = uuid.uuid4().hex  # our own UID namespace (E15)
    base_path = urlsplit(sub.caldav_url).path
    if not base_path.endswith("/"):
        base_path += "/"
    href = f"{base_path}{uid}.ics"
    now = datetime.now(UTC)
    ics_text = ics_write.render_single_vevent(
        uid=uid,
        dtstamp=now,
        title=data.title,
        description=data.description,
        location=data.location,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        all_day=data.all_day,
        busy=data.busy,
        rrule=data.rrule,
        exdates=[],
    )
    try:
        etag = await caldav.put_object(
            url=sub.caldav_url,
            href=href,
            ics_text=ics_text,
            etag=None,
            if_none_match=True,  # a fresh resource must never overwrite (freak collision -> 409)
            auth=auth,
        )
    except CaldavError as exc:
        raise _map_caldav_error(exc) from exc
    if etag is None:  # server sent no PUT ETag — one best-effort refresh (E4)
        try:
            etag = (await caldav.get_object(url=sub.caldav_url, href=href, auth=auth)).etag
        except CaldavError:
            etag = None  # next sync tick restamps; next write is unconditional

    event = CalendarEvent(
        household_id=household_id,
        owner_id=owner_id,
        title=data.title,
        description=data.description,
        location=data.location,
        starts_at=data.starts_at,
        ends_at=data.ends_at,
        all_day=data.all_day,
        layer="personal",
        busy=data.busy,
        kind="normal",
        rrule=data.rrule,
        tzid="UTC",
        subscription_id=sub.id,
        source_uid=uid,
        ext_href=href,
        ext_etag=etag,
    )
    session.add(event)
    await emit(session, type="calendar.event.created", household_id=household_id, payload={})
    await session.flush()
    return event


async def update_event(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    viewer_id: uuid.UUID,
    event_id: uuid.UUID,
    expected_version: int,
    data: EventUpdate,
    caldav: CaldavPort,
) -> CalendarEvent:
    """Patch an event under optimistic concurrency (``expected_version`` = If-Match). 403 if not the
    owner, 412 if stale, 422 if the change makes ``ends_at`` precede ``starts_at``. A mirrored
    event is written through to the external server first (GET-modify-PUT, P9-S4). Emits
    ``calendar.event.updated``."""
    event = await get_event(session, viewer_id=viewer_id, event_id=event_id)
    if event.owner_id != viewer_id:
        raise ProblemException(slug="not_owner", title="Nicht dein Termin", status=403)
    if event.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Termin zwischenzeitlich geändert", status=412
        )
    if event.subscription_id is not None:
        return await _update_mirror_event(
            session, household_id=household_id, event=event, data=data, caldav=caldav
        )
    if data.title is not None:
        event.title = data.title
    if data.description is not None:
        event.description = data.description
    if data.location is not None:
        event.location = data.location
    if data.starts_at is not None:
        event.starts_at = data.starts_at
    if data.ends_at is not None:
        event.ends_at = data.ends_at
    if data.all_day is not None:
        event.all_day = data.all_day
    if data.layer is not None:
        event.layer = data.layer
    if data.busy is not None:
        event.busy = data.busy
    if data.kind is not None:
        event.kind = data.kind
    if data.rrule is not None:
        event.rrule = data.rrule or None  # empty string clears the recurrence
    if data.tzid is not None:
        if not is_valid_tzid(data.tzid):
            raise ProblemException(slug="invalid_tzid", title="Ungültige Zeitzone", status=422)
        event.tzid = data.tzid
    if event.ends_at < event.starts_at:
        raise ProblemException(
            slug="invalid_range", title="Ende darf nicht vor dem Beginn liegen", status=422
        )
    if event.rrule is not None and not is_valid_rrule(event.rrule, dtstart=event.starts_at):
        raise ProblemException(
            slug="invalid_rrule", title="Ungültige Wiederholungsregel", status=422
        )
    await emit(session, type="calendar.event.updated", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(event, attribute_names=["version", "updated_at"])
    return event


async def _update_mirror_event(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    event: CalendarEvent,
    data: EventUpdate,
    caldav: CaldavPort,
) -> CalendarEvent:
    """Write-through edit of a mirror (P9-S4, E12): compute the effective values without
    touching the row, fetch the remote resource, patch ONLY the changed properties in the raw
    document (foreign VALARMs/ATTENDEEs/X-props survive), PUT under the fresh ETag — and only
    then apply the change locally. Any failure leaves the local row untouched (tx rollback)."""
    # Non-round-trippable fields (E7): a change would be flipped back by the next sync tick.
    for field, current in (("layer", event.layer), ("kind", event.kind), ("tzid", event.tzid)):
        requested = getattr(data, field)
        if requested is not None and requested != current:
            raise ProblemException(
                slug="external_field_readonly",
                title="Feld ist bei externen Terminen nicht änderbar",
                status=422,
                extra={"field": field},
            )

    eff: dict[str, Any] = {
        "title": data.title if data.title is not None else event.title,
        "description": data.description if data.description is not None else event.description,
        "location": data.location if data.location is not None else event.location,
        "starts_at": data.starts_at if data.starts_at is not None else event.starts_at,
        "ends_at": data.ends_at if data.ends_at is not None else event.ends_at,
        "all_day": data.all_day if data.all_day is not None else event.all_day,
        "busy": data.busy if data.busy is not None else event.busy,
        # Empty string clears the recurrence (the local-path convention).
        "rrule": (data.rrule or None) if data.rrule is not None else event.rrule,
    }
    changed = {key for key, value in eff.items() if value != getattr(event, key)}
    if not changed:
        return event  # nothing to write — no remote round-trip

    starts = cast(datetime, eff["starts_at"])
    ends = cast(datetime, eff["ends_at"])
    if ends < starts:
        raise ProblemException(
            slug="invalid_range", title="Ende darf nicht vor dem Beginn liegen", status=422
        )
    rrule = cast(str | None, eff["rrule"])
    if rrule is not None and not is_valid_rrule(rrule, dtstart=starts):
        raise ProblemException(
            slug="invalid_rrule", title="Ungültige Wiederholungsregel", status=422
        )

    sub = await _mirror_subscription(session, event)
    auth = _mirror_credentials(sub)
    href = cast(str, event.ext_href)
    try:
        obj = await caldav.get_object(url=sub.caldav_url, href=href, auth=auth)
    except CaldavError as exc:
        raise _map_caldav_error(exc) from exc

    changes = ics_write.build_patch_changes(changed=changed, eff=eff, tzid=event.tzid)
    try:
        new_ics = ics_write.patch_vevent(
            obj.ics_text, uid=cast(str, event.source_uid), changes=changes
        )
    except ics_write.VeventNotFoundError as exc:
        raise _external_conflict() from exc  # remote content changed under us
    try:
        new_etag = await caldav.put_object(
            url=sub.caldav_url,
            href=href,
            ics_text=new_ics,
            etag=obj.etag,  # the FRESH etag from the GET (E3) — minimal race window
            if_none_match=False,
            auth=auth,
        )
    except CaldavError as exc:
        raise _map_caldav_error(exc) from exc
    if new_etag is None:  # server sent no PUT ETag — one best-effort refresh (E4)
        try:
            new_etag = (await caldav.get_object(url=sub.caldav_url, href=href, auth=auth)).etag
        except CaldavError:
            new_etag = None

    # Remote accepted — NOW apply locally (E12).
    for key, value in eff.items():
        setattr(event, key, value)
    if "rrule" in changed and eff["rrule"] is None:
        event.exdates = []  # remote EXDATEs were dropped with the rule (build_patch_changes)
    event.ext_etag = new_etag
    await emit(session, type="calendar.event.updated", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(event, attribute_names=["version", "updated_at"])
    return event


async def delete_event(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    viewer_id: uuid.UUID,
    event_id: uuid.UUID,
    caldav: CaldavPort,
) -> None:
    """Soft-delete an event (403 if not the owner). A mirrored event is deleted on the external
    server first (If-Match on the stored ETag; already-gone counts as success, P9-S4). Emits
    ``calendar.event.deleted``."""
    event = await get_event(session, viewer_id=viewer_id, event_id=event_id)
    if event.owner_id != viewer_id:
        raise ProblemException(slug="not_owner", title="Nicht dein Termin", status=403)
    if event.subscription_id is not None:
        sub = await _mirror_subscription(session, event)
        auth = _mirror_credentials(sub)
        try:
            await caldav.delete_object(
                url=sub.caldav_url,
                href=cast(str, event.ext_href),
                etag=event.ext_etag,  # stored anchor (E3); NULL -> unconditional
                auth=auth,
            )
        except CaldavError as exc:
            if exc.category != "not_found":  # already gone remotely = success
                raise _map_caldav_error(exc) from exc
    event.deleted_at = datetime.now(UTC)
    await emit(session, type="calendar.event.deleted", household_id=household_id, payload={})


# --- Single-occurrence exceptions (EXDATE, P5-S5, ADR-0043) -------------------


async def _series_for_exception(
    session: AsyncSession, *, viewer_id: uuid.UUID, event_id: uuid.UUID
) -> tuple[CalendarEvent, str]:
    """Load a recurring event the caller owns, ready to amend its EXDATE set, and return it with its
    (non-null) RRULE. 404 if not visible, 403 if not the owner, 422 if it is not a series (a one-off
    has no occurrences to cancel)."""
    event = await get_event(session, viewer_id=viewer_id, event_id=event_id)
    if event.owner_id != viewer_id:
        raise ProblemException(slug="not_owner", title="Nicht dein Termin", status=403)
    _reject_external(event)
    if event.rrule is None:
        raise ProblemException(slug="not_a_series", title="Termin ist keine Serie", status=422)
    return event, event.rrule


async def cancel_occurrence(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    viewer_id: uuid.UUID,
    event_id: uuid.UUID,
    occurrence_start: datetime,
) -> CalendarEvent:
    """Cancel a single occurrence of a series by adding its start to the EXDATE set (owner-only).
    422 if ``occurrence_start`` is not a real occurrence of the rule. Idempotent: cancelling an
    already-cancelled instance is a no-op. Emits ``calendar.event.updated``."""
    event, rrule = await _series_for_exception(session, viewer_id=viewer_id, event_id=event_id)
    if not is_occurrence(event.starts_at, rrule, occurrence_start, tzid=event.tzid):
        raise ProblemException(slug="not_an_occurrence", title="Kein Termin der Serie", status=422)
    target = as_utc_instant(occurrence_start)
    if all(as_utc_instant(dt) != target for dt in event.exdates):
        # Reassign (not .append) so SQLAlchemy detects the mutation of the ARRAY column.
        event.exdates = [*event.exdates, occurrence_start]
        await emit(session, type="calendar.event.updated", household_id=household_id, payload={})
        await session.flush()
        await session.refresh(event, attribute_names=["version", "updated_at"])
    return event


async def restore_occurrence(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    viewer_id: uuid.UUID,
    event_id: uuid.UUID,
    occurrence_start: datetime,
) -> CalendarEvent:
    """Undo a cancellation: remove ``occurrence_start`` from the EXDATE set (owner-only). A no-op if
    it was not cancelled. Emits ``calendar.event.updated``."""
    event, _ = await _series_for_exception(session, viewer_id=viewer_id, event_id=event_id)
    target = as_utc_instant(occurrence_start)
    remaining = [dt for dt in event.exdates if as_utc_instant(dt) != target]
    if len(remaining) != len(event.exdates):
        event.exdates = remaining
        await emit(session, type="calendar.event.updated", household_id=household_id, payload={})
        await session.flush()
        await session.refresh(event, attribute_names=["version", "updated_at"])
    return event


async def move_occurrence(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    viewer_id: uuid.UUID,
    event_id: uuid.UUID,
    occurrence_start: datetime,
    new_start: datetime,
    new_end: datetime,
) -> CalendarEvent:
    """Move a single occurrence of a series to a new time (owner-only, P5-S10). 422 if
    ``occurrence_start`` is not a real occurrence, if it is cancelled (EXDATE), or if ``new_end``
    precedes ``new_start``. Stores/updates the override keyed by the original instant. Emits
    ``calendar.event.updated``."""
    event, rrule = await _series_for_exception(session, viewer_id=viewer_id, event_id=event_id)
    if not is_occurrence(event.starts_at, rrule, occurrence_start, tzid=event.tzid):
        raise ProblemException(slug="not_an_occurrence", title="Kein Termin der Serie", status=422)
    if new_end < new_start:
        raise ProblemException(
            slug="invalid_range", title="Ende darf nicht vor dem Beginn liegen", status=422
        )
    target = as_utc_instant(occurrence_start)
    if any(as_utc_instant(dt) == target for dt in event.exdates):
        raise ProblemException(slug="occurrence_cancelled", title="Termin ist abgesagt", status=422)
    overrides = dict(event.overrides or {})
    overrides[occurrence_key(occurrence_start)] = {
        "starts_at": as_utc_instant(new_start).isoformat(),
        "ends_at": as_utc_instant(new_end).isoformat(),
    }
    event.overrides = overrides  # reassign so SQLAlchemy detects the JSONB mutation
    await emit(session, type="calendar.event.updated", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(event, attribute_names=["version", "updated_at"])
    return event


async def reset_occurrence(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    viewer_id: uuid.UUID,
    event_id: uuid.UUID,
    occurrence_start: datetime,
) -> CalendarEvent:
    """Undo a move: drop the override for ``occurrence_start`` so it returns to its rule time
    (owner-only). No-op if it was not moved. Emits ``calendar.event.updated``."""
    event, _ = await _series_for_exception(session, viewer_id=viewer_id, event_id=event_id)
    key = occurrence_key(occurrence_start)
    if key in (event.overrides or {}):
        overrides = dict(event.overrides)
        del overrides[key]
        event.overrides = overrides
        await emit(session, type="calendar.event.updated", household_id=household_id, payload={})
        await session.flush()
        await session.refresh(event, attribute_names=["version", "updated_at"])
    return event


# --- ICS import (P5-S6, ADR-0044) --------------------------------------------


async def import_ics(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    owner_id: uuid.UUID,
    content: str,
    layer: str,
) -> tuple[int, int, int]:
    """Import every VEVENT in ``content`` as an event owned by the caller in ``layer``. Returns
    ``(imported, skipped, failed)``: ``skipped`` = a VEVENT whose UID is already present in the
    household (re-import is idempotent), ``failed`` = an event with an invalid RRULE. Emits a single
    ``calendar.event.created`` if anything was imported (one SSE refresh)."""
    parsed = parse_ics(content)
    seen_uids = {p.uid for p in parsed if p.uid is not None}
    existing: set[str] = set()
    if seen_uids:
        rows = await session.scalars(
            select(CalendarEvent.source_uid).where(
                CalendarEvent.source_uid.in_(seen_uids),
                CalendarEvent.deleted_at.is_(None),
                # Mirror rows (P9-S3) keep their own UID namespace per subscription — an ICS
                # import must not treat them as "already imported".
                CalendarEvent.subscription_id.is_(None),
            )
        )
        existing = {uid for uid in rows if uid is not None}

    imported = skipped = failed = 0
    for ev in parsed:
        if ev.uid is not None and ev.uid in existing:
            skipped += 1
            continue
        if ev.rrule is not None and not is_valid_rrule(ev.rrule, dtstart=ev.starts_at):
            failed += 1
            continue
        session.add(
            CalendarEvent(
                household_id=household_id,
                owner_id=owner_id,
                title=ev.title,
                description=ev.description,
                location=ev.location,
                starts_at=ev.starts_at,
                ends_at=ev.ends_at,
                all_day=ev.all_day,
                # TRANSP:TRANSPARENT marks a non-blocking event (P9-S3 parser addition) — an
                # imported birthday should not occupy scheduling slots either.
                busy=not ev.transparent,
                layer=layer,
                rrule=ev.rrule,
                exdates=ev.exdates,
                source_uid=ev.uid,
            )
        )
        if ev.uid is not None:
            existing.add(ev.uid)  # dedupe duplicates within the same file too
        imported += 1

    if imported:
        await emit(session, type="calendar.event.created", household_id=household_id, payload={})
        await session.flush()
    return imported, skipped, failed


async def list_busy_intervals(
    session: AsyncSession,
    *,
    viewer_id: uuid.UUID,
    frm: datetime,
    to: datetime,
) -> list[tuple[datetime, datetime]]:
    """The viewer's occupied ``(start, end)`` intervals within ``[frm, to]`` — every visible event
    flagged ``busy`` (household-layer + own personal), recurring series expanded and EXDATEs
    honoured. The seam the scheduling engine reads (via ``calendar.api``) to avoid double-booking;
    intervals are not merged (the caller does that). RLS keeps it within the household."""
    rows = list(
        await session.scalars(
            _visible(select(CalendarEvent), viewer_id=viewer_id).where(
                CalendarEvent.deleted_at.is_(None), CalendarEvent.busy.is_(True)
            )
        )
    )
    intervals: list[tuple[datetime, datetime]] = []
    for event in rows:
        for _orig, occ_start, occ_end in expand_occurrences(
            event.starts_at,
            event.ends_at,
            event.rrule,
            frm,
            to,
            event.exdates,
            event.tzid,
            _overrides(event),
        ):
            intervals.append((occ_start, occ_end))
    intervals.sort(key=lambda iv: iv[0])
    return intervals


async def list_absence_intervals(
    session: AsyncSession,
    *,
    viewer_id: uuid.UUID,
    frm: datetime,
    to: datetime,
) -> list[tuple[datetime, datetime]]:
    """The viewer's **own** ``absence`` intervals within ``[frm, to]`` (expanded, EXDATE honoured).
    The scheduling seam (via ``calendar.api``) so a member is never offered a slot while away.
    Scoped to ``owner_id == viewer_id`` — a housemate's absence does not block my scheduling."""
    rows = list(
        await session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.deleted_at.is_(None),
                CalendarEvent.kind == "absence",
                CalendarEvent.owner_id == viewer_id,
            )
        )
    )
    intervals: list[tuple[datetime, datetime]] = []
    for event in rows:
        for _orig, occ_start, occ_end in expand_occurrences(
            event.starts_at,
            event.ends_at,
            event.rrule,
            frm,
            to,
            event.exdates,
            event.tzid,
            _overrides(event),
        ):
            intervals.append((occ_start, occ_end))
    intervals.sort(key=lambda iv: iv[0])
    return intervals


async def list_absences(
    session: AsyncSession, *, frm: datetime | None = None, to: datetime | None = None
) -> list[CalendarEvent]:
    """All household ``absence`` events (RLS-scoped), optionally overlapping ``[frm, to]`` — the
    seam the scheduling/fairness logic reads via ``calendar.api`` to know who is away (P5-S4).
    Recurring absences are returned as their master (the caller expands). Layer-agnostic: an
    absence blocks scheduling regardless of household/personal layer."""
    stmt = select(CalendarEvent).where(
        CalendarEvent.deleted_at.is_(None), CalendarEvent.kind == "absence"
    )
    if to is not None:
        stmt = stmt.where(CalendarEvent.starts_at <= to)
    if frm is not None:
        stmt = stmt.where(CalendarEvent.ends_at >= frm)
    rows = await session.scalars(stmt.order_by(CalendarEvent.starts_at))
    return list(rows)


# --- ICS subscription feed (P5-S3, ADR-0042) ---------------------------------


async def ensure_feed(
    session: AsyncSession, *, household_id: uuid.UUID, member_id: uuid.UUID
) -> CalendarFeed:
    """Return the caller's feed, creating it (or rotating an existing token) — so the URL the user
    sees is always current and any previously shared link is revoked on regenerate."""
    feed = await session.scalar(
        select(CalendarFeed).where(
            CalendarFeed.member_id == member_id, CalendarFeed.deleted_at.is_(None)
        )
    )
    token = secrets.token_urlsafe(32)
    if feed is None:
        feed = CalendarFeed(household_id=household_id, member_id=member_id, token=token)
        session.add(feed)
    else:
        feed.token = token
    await session.flush()
    return feed


async def revoke_feed(session: AsyncSession, *, member_id: uuid.UUID) -> None:
    """Soft-delete the caller's feed (the shared URL stops working). No-op if none exists."""
    feed = await session.scalar(
        select(CalendarFeed).where(
            CalendarFeed.member_id == member_id, CalendarFeed.deleted_at.is_(None)
        )
    )
    if feed is not None:
        feed.deleted_at = datetime.now(UTC)


async def resolve_feed(session: AsyncSession, *, token: str) -> CalendarFeed | None:
    """Resolve a feed token cross-household (maint session; ``maint_all`` policy). Returns the
    active feed or None — the entry point for the unauthenticated ICS endpoint."""
    feed: CalendarFeed | None = await session.scalar(
        select(CalendarFeed).where(CalendarFeed.token == token, CalendarFeed.deleted_at.is_(None))
    )
    return feed


async def list_for_feed(session: AsyncSession, *, viewer_id: uuid.UUID) -> list[CalendarEvent]:
    """All visible events for the member (RLS-scoped), **not** expanded — the ICS feed emits each
    recurring master with its RRULE and lets the subscriber's client expand it."""
    rows = await session.scalars(
        _visible(select(CalendarEvent), viewer_id=viewer_id)
        .where(CalendarEvent.deleted_at.is_(None))
        .order_by(CalendarEvent.starts_at)
    )
    return list(rows)


# --- External CalDAV subscriptions (P9-S2) ------------------------------------
# Subscriptions are personal (foreign URLs + credentials): RLS isolates the household, every read
# here additionally filters member_id — a co-member's (or admin's) subscription answers 404, like
# a foreign personal event (ADR-0040 idea). Credentials are encrypted in this layer only (one
# place guarantees plaintext is never persisted); the crypto box is required solely on writes that
# actually carry credentials, so the feature stays usable without a key (Graceful Enhancement).


async def get_subscription(
    session: AsyncSession, *, member_id: uuid.UUID, subscription_id: uuid.UUID
) -> ExternalCalendarSubscription:
    """Fetch one of the caller's subscriptions (404 if missing, soft-deleted, or foreign)."""
    sub = await session.get(ExternalCalendarSubscription, subscription_id)
    if sub is None or sub.deleted_at is not None or sub.member_id != member_id:
        raise ProblemException(slug="not_found", title="Abo nicht gefunden", status=404)
    return sub


async def list_subscriptions(
    session: AsyncSession, *, member_id: uuid.UUID
) -> list[ExternalCalendarSubscription]:
    """The caller's active subscriptions, oldest first (stable UI order)."""
    rows = await session.scalars(
        select(ExternalCalendarSubscription)
        .where(
            ExternalCalendarSubscription.member_id == member_id,
            ExternalCalendarSubscription.deleted_at.is_(None),
        )
        .order_by(ExternalCalendarSubscription.created_at)
    )
    return list(rows)


async def _reject_duplicate_url(
    session: AsyncSession,
    *,
    member_id: uuid.UUID,
    caldav_url: str,
    exclude_id: uuid.UUID | None = None,
) -> None:
    """Friendly 409 before the partial unique index (member_id, caldav_url) fires on a race."""
    stmt = select(ExternalCalendarSubscription.id).where(
        ExternalCalendarSubscription.member_id == member_id,
        ExternalCalendarSubscription.caldav_url == caldav_url,
        ExternalCalendarSubscription.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(ExternalCalendarSubscription.id != exclude_id)
    if await session.scalar(stmt) is not None:
        raise ProblemException(
            slug="subscription_exists", title="Abo für diese URL existiert bereits", status=409
        )


async def create_subscription(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    data: SubscriptionCreate,
) -> ExternalCalendarSubscription:
    """Create a subscription owned by the caller. With credentials the crypto key is required
    (503 without one, ADR-0077); without them the row is anonymous and works keyless. 409 on a
    second active subscription for the same URL. Emits ``calendar.subscription.created``."""
    await _reject_duplicate_url(session, member_id=member_id, caldav_url=data.caldav_url)
    creds_enc: str | None = None
    if data.username is not None and data.password is not None:
        box = require_secretbox()
        creds_enc = encode_credentials(box, username=data.username, password=data.password)
    sub = ExternalCalendarSubscription(
        household_id=household_id,
        member_id=member_id,
        label=data.label,
        caldav_url=data.caldav_url,
        creds_enc=creds_enc,
        enabled=data.enabled,
    )
    session.add(sub)
    await emit(session, type="calendar.subscription.created", household_id=household_id, payload={})
    await session.flush()
    return sub


async def update_subscription(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    subscription_id: uuid.UUID,
    expected_version: int,
    data: SubscriptionUpdate,
) -> ExternalCalendarSubscription:
    """Patch a subscription under If-Match (412 stale). ``username``+``password`` replace the
    stored credentials (crypto key required → 503 without one); ``clear_credentials`` drops them
    keyless; omitted credential fields leave them unchanged. Emits
    ``calendar.subscription.updated``."""
    sub = await get_subscription(session, member_id=member_id, subscription_id=subscription_id)
    if sub.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Abo zwischenzeitlich geändert", status=412
        )
    if data.caldav_url is not None and data.caldav_url != sub.caldav_url:
        await _reject_duplicate_url(
            session, member_id=member_id, caldav_url=data.caldav_url, exclude_id=sub.id
        )
        sub.caldav_url = data.caldav_url
    if data.label is not None:
        sub.label = data.label
    if data.enabled is not None:
        sub.enabled = data.enabled
    if data.clear_credentials:
        sub.creds_enc = None
    elif data.username is not None and data.password is not None:
        box = require_secretbox()
        sub.creds_enc = encode_credentials(box, username=data.username, password=data.password)
    await emit(session, type="calendar.subscription.updated", household_id=household_id, payload={})
    await session.flush()
    await session.refresh(sub, attribute_names=["version", "updated_at"])
    return sub


@dataclass(frozen=True)
class CheckResult:
    """Outcome of a connection probe. ``category`` is the same slug family the sync records in
    ``last_sync_error`` (``auth_failed``, ``unreachable``, …), so the web reuses one message map."""

    ok: bool
    category: str | None = None
    objects: int | None = None


async def check_subscription(
    session: AsyncSession,
    *,
    caldav: CaldavPort,
    member_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> CheckResult:
    """Probe the stored URL + credentials once and report what happened, now.

    Without this, the only way to learn that a URL or a password is wrong is to wait for the
    15-minute cron and read ``last_sync_error`` — which makes setting up a subscription a
    guessing game with a quarter-hour feedback loop.

    Deliberately a **pure probe**: it reads one collection listing and writes nothing — not the
    mirrors, not ``last_sync_at``, not even ``last_sync_error``. A "check" that mutates state
    would be a second, half-hearted sync path, and the next cron tick records the truth anyway.

    Errors are answered as data (``ok=False`` + category), not raised: a failing probe is the
    expected outcome of a typo, not a server fault. Only the crypto-key case still raises, since
    that is a deployment problem the member cannot act on."""
    sub = await get_subscription(session, member_id=member_id, subscription_id=subscription_id)
    auth = ANONYMOUS
    if sub.creds_enc is not None:
        box = get_secretbox()
        if box is None:
            raise ProblemException(
                slug="crypto_unconfigured",
                title="Verschlüsselung nicht konfiguriert",
                status=503,
                detail="Diese Funktion braucht einen Server-Schlüssel (CUSTODE_CRYPTO_KEY). "
                "Bitte den Betreiber kontaktieren.",
            )
        try:
            username, password = decode_credentials(box, sub.creds_enc)
        except SecretBoxError:
            return CheckResult(ok=False, category="creds_undecryptable")
        auth = CaldavAuth(username=username, password=password)

    try:
        objects = await caldav.list_objects(url=sub.caldav_url, auth=auth)
    except CaldavError as exc:
        return CheckResult(ok=False, category=exc.category)
    return CheckResult(ok=True, objects=len(objects))


async def delete_subscription(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    member_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> None:
    """Soft-delete a subscription (the partial unique index then allows re-subscribing) and, in
    the same transaction, its mirrored events (P9-S3 — a mirror without its source is dead
    weight; ``enabled=false`` is the non-destructive pause). Emits
    ``calendar.subscription.deleted`` (+ one ``calendar.event.deleted`` if mirrors existed)."""
    sub = await get_subscription(session, member_id=member_id, subscription_id=subscription_id)
    now = datetime.now(UTC)
    result = cast(
        CursorResult[Any],
        await session.execute(
            update(CalendarEvent)
            .where(CalendarEvent.subscription_id == sub.id, CalendarEvent.deleted_at.is_(None))
            .values(deleted_at=now)
        ),
    )
    sub.deleted_at = now
    if result.rowcount:
        await emit(session, type="calendar.event.deleted", household_id=household_id, payload={})
    await emit(session, type="calendar.subscription.deleted", household_id=household_id, payload={})
