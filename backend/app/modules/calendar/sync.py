"""CalDAV pull-sync (P9-S3, ADR-0079): mirror every enabled subscription's events into
``calendar_events``.

Run shape (15-min worker cron): enumerate subscriptions under the maint session (SELECT-only
``maint_all`` policy, migration 0065 — MUST filter ``deleted_at IS NULL AND enabled``, BUGLOG
2026-07-08), then per subscription fetch + parse + diff **under the owner's** ``scoped_session``
(RLS enforced; the maint role cannot write these tables by design).

Mirrored rows are ``layer='personal'`` events owned by the subscriber — they feed the owner's
„belegt"-signal automatically (Synergie S-16 via ``list_busy_intervals``) and stay invisible to
co-members. ``busy = NOT transparent`` (birthdays don't block), ``tzid`` preserved when resolvable
(DST-correct series, ADR-0047). Failure isolation is three-tiered: a broken VEVENT is skipped, a
broken subscription records ``last_sync_error`` and the loop continues, a broken run logs and the
next tick retries. Logs carry aggregate counts only — never URLs, credentials, or event content."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.crypto import SecretBoxError, get_secretbox
from app.kernel.events.emit import emit
from app.kernel.ports.caldav import ANONYMOUS, CaldavAuth, CaldavError, CaldavObject, CaldavPort
from app.kernel.tenancy.session import maint_session, scoped_session
from app.logging import get_logger
from app.modules.calendar.creds import decode_credentials
from app.modules.calendar.expand import as_utc_instant, is_valid_rrule, is_valid_tzid
from app.modules.calendar.ics_parse import ParsedIcsEvent, parse_ics
from app.modules.calendar.models import CalendarEvent, ExternalCalendarSubscription

_log = get_logger("calendar.sync")


@dataclass
class SyncStats:
    """Aggregate outcome of one sync run (the only thing that is ever logged)."""

    subscriptions: int = 0
    synced: int = 0
    failed: int = 0
    created: int = 0
    updated: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class _SubRef:
    """Detached snapshot of one subscription (the maint session is closed before fetching)."""

    id: uuid.UUID
    household_id: uuid.UUID
    member_id: uuid.UUID
    caldav_url: str
    creds_enc: str | None


class _SyncSkip(Exception):
    """Subscription-level skip with a ``last_sync_error`` category (mirrors ``CaldavError``)."""

    def __init__(self, category: str) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class _Wanted:
    """One mirror-worthy master VEVENT plus its resource context (write-back anchors, 9-S4)."""

    ev: ParsedIcsEvent
    href: str
    etag: str | None


def _build_wanted(objects: list[CaldavObject]) -> dict[str, _Wanted]:
    """Pure: reduce the fetched calendar objects to the mirror-worthy master VEVENTs, keyed by
    UID. Skips events without a UID (no stable diff key), RECURRENCE-ID overrides (the master
    wins — mirroring moved single occurrences is a documented gap), invalid RRULEs and inverted
    ranges; ``STATUS:CANCELLED`` removes the UID entirely (treated like remotely deleted)."""
    wanted: dict[str, _Wanted] = {}
    cancelled: set[str] = set()
    for obj in objects:
        for ev in parse_ics(obj.ics_text):
            if ev.uid is None:
                continue
            if ev.recurrence_id is not None:
                continue
            if ev.cancelled:
                cancelled.add(ev.uid)
                continue
            if ev.ends_at < ev.starts_at:
                continue  # would violate the ends_at >= starts_at CHECK
            if ev.rrule is not None and not is_valid_rrule(ev.rrule, dtstart=ev.starts_at):
                continue
            if ev.uid not in wanted:  # first occurrence wins on feed-internal duplicates
                wanted[ev.uid] = _Wanted(ev=ev, href=obj.href, etag=obj.etag)
    for uid in cancelled:
        wanted.pop(uid, None)
    return wanted


def _mirror_fields(ev: ParsedIcsEvent) -> dict[str, object]:
    """The mutable column set of a mirror row (remote data is length-capped defensively)."""
    return {
        "title": (ev.title or "(ohne Titel)")[:200],
        "description": ev.description,
        "location": ev.location[:200] if ev.location else None,
        "starts_at": ev.starts_at,
        "ends_at": ev.ends_at,
        "all_day": ev.all_day,
        "busy": not ev.transparent,
        "rrule": ev.rrule,
        "exdates": list(ev.exdates),
        "tzid": ev.tzid if ev.tzid and is_valid_tzid(ev.tzid) else "UTC",
    }


def _differs(row: CalendarEvent, fields: dict[str, object]) -> bool:
    for key, value in fields.items():
        current: object = getattr(row, key)
        if key == "exdates":
            new_exdates = value if isinstance(value, list) else []
            old_exdates = current if isinstance(current, list) else []
            if {as_utc_instant(d) for d in old_exdates} != {as_utc_instant(d) for d in new_exdates}:
                return True
        elif current != value:
            return True
    return False


async def _apply_diff(
    session: AsyncSession,
    *,
    sub: _SubRef,
    wanted: dict[str, _Wanted],
    now: datetime,
) -> tuple[int, int, int]:
    """Create/update/soft-delete mirror rows so they match ``wanted``. Runs under the owner's
    scoped session; the partial unique index (subscription_id, source_uid) backstops races.
    ``ext_href``/``ext_etag`` are stamped on EVERY run (the server may rotate ETags without
    field changes; a stale anchor would fail a later If-Match) — but only a semantic field
    change counts as ``updated``/triggers the SSE emit."""
    existing = {
        e.source_uid: e
        for e in await session.scalars(
            select(CalendarEvent).where(
                CalendarEvent.subscription_id == sub.id, CalendarEvent.deleted_at.is_(None)
            )
        )
    }
    created = updated = deleted = 0
    for uid, w in wanted.items():
        fields = _mirror_fields(w.ev)
        row = existing.pop(uid, None)
        if row is None:
            session.add(
                CalendarEvent(
                    household_id=sub.household_id,
                    owner_id=sub.member_id,
                    subscription_id=sub.id,
                    source_uid=uid,
                    layer="personal",
                    kind="normal",
                    ext_href=w.href,
                    ext_etag=w.etag,
                    **fields,
                )
            )
            created += 1
        else:
            if _differs(row, fields):
                for key, value in fields.items():
                    setattr(row, key, value)
                updated += 1
            row.ext_href = w.href  # unconditional restamp (heals 9-S3 rows, tracks etag drift)
            row.ext_etag = w.etag
    for row in existing.values():  # vanished remotely (or newly CANCELLED)
        row.deleted_at = now
        deleted += 1
    return created, updated, deleted


async def _record_error(sub: _SubRef, category: str) -> None:
    """Best-effort ``last_sync_error`` stamp; ``last_sync_at`` (= last success) stays put."""
    try:
        async with scoped_session(household_id=sub.household_id, user_id=sub.member_id) as session:
            row = await session.get(ExternalCalendarSubscription, sub.id)
            if row is not None and row.deleted_at is None:
                row.last_sync_error = category[:200]
    except Exception:
        _log.warning("caldav_sync_error_stamp_failed", subscription_id=str(sub.id))


async def sync_all_subscriptions(*, caldav: CaldavPort, now: datetime) -> SyncStats:
    """One full sync run over every enabled subscription. Called by the worker cron with the
    composed ``CaldavPort`` (real client or Null when the kill switch is off)."""
    stats = SyncStats()
    box = get_secretbox()

    async with maint_session() as ms:
        rows = await ms.execute(
            select(
                ExternalCalendarSubscription.id,
                ExternalCalendarSubscription.household_id,
                ExternalCalendarSubscription.member_id,
                ExternalCalendarSubscription.caldav_url,
                ExternalCalendarSubscription.creds_enc,
            )
            .where(
                ExternalCalendarSubscription.deleted_at.is_(None),
                ExternalCalendarSubscription.enabled.is_(True),
            )
            .order_by(ExternalCalendarSubscription.created_at)
        )
        subs = [_SubRef(*row) for row in rows.all()]
    stats.subscriptions = len(subs)

    for sub in subs:
        try:
            auth = ANONYMOUS
            if sub.creds_enc is not None:
                if box is None:
                    # No server crypto key: credentialed subscriptions pause, anonymous ones
                    # keep syncing (Graceful Enhancement, ADR-0077).
                    raise _SyncSkip("crypto_unconfigured")
                try:
                    username, password = decode_credentials(box, sub.creds_enc)
                except SecretBoxError as exc:
                    raise _SyncSkip("creds_undecryptable") from exc
                auth = CaldavAuth(username=username, password=password)

            objects = await caldav.list_objects(url=sub.caldav_url, auth=auth)
            wanted = _build_wanted(objects)

            created = updated = deleted = 0
            async with scoped_session(
                household_id=sub.household_id, user_id=sub.member_id
            ) as session:
                row = await session.get(ExternalCalendarSubscription, sub.id)
                if row is None or row.deleted_at is not None or not row.enabled:
                    continue  # raced with unsubscribe/pause between enumeration and now
                created, updated, deleted = await _apply_diff(
                    session, sub=sub, wanted=wanted, now=now
                )
                row.last_sync_at = now
                row.last_sync_error = None
                if created or updated or deleted:
                    # One SSE refresh per changed household (import_ics precedent).
                    await emit(
                        session,
                        type="calendar.event.updated",
                        household_id=sub.household_id,
                        payload={},
                    )
            stats.synced += 1
            stats.created += created
            stats.updated += updated
            stats.deleted += deleted
        except (CaldavError, _SyncSkip) as exc:
            await _record_error(sub, exc.category)
            stats.failed += 1
        except Exception:
            # Unexpected failure: isolate, log the class-of-problem only, keep the loop alive.
            _log.exception("caldav_sync_subscription_failed", subscription_id=str(sub.id))
            stats.failed += 1

    _log.info(
        "caldav_sync_done",
        subscriptions=stats.subscriptions,
        synced=stats.synced,
        failed=stats.failed,
        created=stats.created,
        updated=stats.updated,
        deleted=stats.deleted,
    )
    return stats
