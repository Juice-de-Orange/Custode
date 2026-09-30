"""HTTP layer for ``calendar`` (KONZEPT §5.11). Thin: validate -> service -> response. Events are
household-scoped (RLS) with PATCH + If-Match (ADR-0034); GET/POST carry an ETag (= version). Layer
visibility is enforced in the service (ADR-0040). Authoring is member/admin (children get a
calendar in a later slice); CSRF on writes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession, require_role
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.ports.caldav import CaldavPort, get_caldav
from app.kernel.tenancy.session import maint_session, scoped_session
from app.modules.calendar import service
from app.modules.calendar.ics import render_ics
from app.modules.calendar.models import CalendarEvent, ExternalCalendarSubscription
from app.modules.calendar.schemas import (
    EventCreate,
    EventResponse,
    EventUpdate,
    FeedResponse,
    IcsImportRequest,
    IcsImportResult,
    OccurrenceMove,
    OccurrenceRef,
    SubscriptionCheckResponse,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscriptionUpdate,
)
from app.settings import get_settings

calendar_router = APIRouter(prefix="/v1/calendar", tags=["calendar"])

# Authoring events is member/admin in this slice (children excluded).
AuthorPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _event_response(
    event: CalendarEvent,
    starts_at: datetime | None = None,
    ends_at: datetime | None = None,
    original_start: datetime | None = None,
) -> EventResponse:
    """Map an event (or one expanded occurrence — pass its ``starts_at``/``ends_at`` and
    ``original_start``) to the wire shape. ``series_id``/``id`` are the master id; ``recurring``
    reflects the RRULE; ``original_start`` is the cancel/move key for a recurring occurrence."""
    return EventResponse(
        id=event.id,
        series_id=event.id,
        owner_id=event.owner_id,
        title=event.title,
        description=event.description,
        location=event.location,
        starts_at=starts_at if starts_at is not None else event.starts_at,
        ends_at=ends_at if ends_at is not None else event.ends_at,
        original_start=original_start,
        all_day=event.all_day,
        layer=event.layer,
        busy=event.busy,
        kind=event.kind,
        rrule=event.rrule,
        recurring=event.rrule is not None,
        exdates=list(event.exdates),
        tzid=event.tzid,
        external=event.subscription_id is not None,
    )


@calendar_router.get("/events")
async def list_events(
    principal: CurrentPrincipal,
    session: ScopedSession,
    frm: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
) -> list[EventResponse]:
    """Visible occurrences (household-layer + own personal), optionally within from/to. Recurring
    series are expanded into concrete occurrences."""
    _require_household(principal)
    occurrences = await service.list_events(session, viewer_id=principal.user_id, frm=frm, to=to)
    return [
        _event_response(ev, occ_start, occ_end, orig if ev.rrule is not None else None)
        for ev, orig, occ_start, occ_end in occurrences
    ]


@calendar_router.post(
    "/events", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_event(
    payload: EventCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
    caldav: Annotated[CaldavPort, Depends(get_caldav)],
) -> EventResponse:
    """With ``subscription_id`` the event is created in the external CalDAV calendar first
    (synchronous write-through, P9-S4): 409 external_conflict, 502 caldav_write_failed,
    503 caldav_disabled/crypto_unconfigured on remote/composition failures."""
    household_id = _require_household(principal)
    event = await service.create_event(
        session, household_id=household_id, owner_id=principal.user_id, data=payload, caldav=caldav
    )
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


@calendar_router.get("/events/{event_id}")
async def get_event(
    event_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession, response: Response
) -> EventResponse:
    _require_household(principal)
    event = await service.get_event(session, viewer_id=principal.user_id, event_id=event_id)
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


@calendar_router.patch("/events/{event_id}", dependencies=[Depends(require_csrf)])
async def update_event(
    event_id: uuid.UUID,
    payload: EventUpdate,
    request: Request,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
    caldav: Annotated[CaldavPort, Depends(get_caldav)],
) -> EventResponse:
    """A mirrored event is written through to the external server first (GET-modify-PUT under
    the fresh remote ETag, P9-S4) — the local change applies only after the remote accepted."""
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    event = await service.update_event(
        session,
        household_id=household_id,
        viewer_id=principal.user_id,
        event_id=event_id,
        expected_version=expected,
        data=payload,
        caldav=caldav,
    )
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


@calendar_router.delete(
    "/events/{event_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_event(
    event_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
    caldav: Annotated[CaldavPort, Depends(get_caldav)],
) -> None:
    """A mirrored event is deleted on the external server first (If-Match, P9-S4)."""
    household_id = _require_household(principal)
    await service.delete_event(
        session,
        household_id=household_id,
        viewer_id=principal.user_id,
        event_id=event_id,
        caldav=caldav,
    )


# --- Single-occurrence exceptions (EXDATE, P5-S5, ADR-0043) -------------------
# Set-semantics writes (cancel = add to EXDATE, restore = remove): idempotent + commutative, so no
# If-Match — two members cancelling different instances never spuriously 412 each other (ADR-0043).


@calendar_router.post("/events/{event_id}/cancel-occurrence", dependencies=[Depends(require_csrf)])
async def cancel_occurrence(
    event_id: uuid.UUID,
    payload: OccurrenceRef,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> EventResponse:
    """Cancel a single occurrence of a recurring series (owner-only). 422 if the event is not a
    series or the date is not one of its occurrences."""
    household_id = _require_household(principal)
    event = await service.cancel_occurrence(
        session,
        household_id=household_id,
        viewer_id=principal.user_id,
        event_id=event_id,
        occurrence_start=payload.occurrence_start,
    )
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


@calendar_router.post("/events/{event_id}/restore-occurrence", dependencies=[Depends(require_csrf)])
async def restore_occurrence(
    event_id: uuid.UUID,
    payload: OccurrenceRef,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> EventResponse:
    """Undo a cancellation — re-add a previously cancelled occurrence to the series (owner-only)."""
    household_id = _require_household(principal)
    event = await service.restore_occurrence(
        session,
        household_id=household_id,
        viewer_id=principal.user_id,
        event_id=event_id,
        occurrence_start=payload.occurrence_start,
    )
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


@calendar_router.post("/events/{event_id}/move-occurrence", dependencies=[Depends(require_csrf)])
async def move_occurrence(
    event_id: uuid.UUID,
    payload: OccurrenceMove,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> EventResponse:
    """Move a single occurrence of a series to a new time (owner-only). 422 if the date is not one
    of its occurrences, is cancelled, or the new range is inverted."""
    household_id = _require_household(principal)
    event = await service.move_occurrence(
        session,
        household_id=household_id,
        viewer_id=principal.user_id,
        event_id=event_id,
        occurrence_start=payload.occurrence_start,
        new_start=payload.new_start,
        new_end=payload.new_end,
    )
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


@calendar_router.post("/events/{event_id}/reset-occurrence", dependencies=[Depends(require_csrf)])
async def reset_occurrence(
    event_id: uuid.UUID,
    payload: OccurrenceRef,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> EventResponse:
    """Undo a move — return a moved occurrence to its rule time (owner-only)."""
    household_id = _require_household(principal)
    event = await service.reset_occurrence(
        session,
        household_id=household_id,
        viewer_id=principal.user_id,
        event_id=event_id,
        occurrence_start=payload.occurrence_start,
    )
    response.headers["ETag"] = f'"{event.version}"'
    return _event_response(event)


# --- ICS import (P5-S6, ADR-0044) --------------------------------------------


@calendar_router.post("/import", dependencies=[Depends(require_csrf)])
async def import_ics(
    payload: IcsImportRequest, principal: AuthorPrincipal, session: ScopedSession
) -> IcsImportResult:
    """Import an uploaded iCalendar file (raw text — no URL fetch, so no SSRF). Events land in the
    chosen layer, owned by the caller; re-importing the same file is idempotent (UID dedup)."""
    household_id = _require_household(principal)
    imported, skipped, failed = await service.import_ics(
        session,
        household_id=household_id,
        owner_id=principal.user_id,
        content=payload.content,
        layer=payload.layer,
    )
    return IcsImportResult(imported=imported, skipped=skipped, failed=failed)


# --- ICS subscription feed (P5-S3, ADR-0042) ---------------------------------


def _feed_url(token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/v1/calendar/feed/{token}.ics"


@calendar_router.post("/feed", dependencies=[Depends(require_csrf)])
async def create_feed(principal: AuthorPrincipal, session: ScopedSession) -> FeedResponse:
    """Create or **rotate** the caller's secret ICS subscription URL (any old link is revoked)."""
    household_id = _require_household(principal)
    feed = await service.ensure_feed(
        session, household_id=household_id, member_id=principal.user_id
    )
    return FeedResponse(url=_feed_url(feed.token))


@calendar_router.delete(
    "/feed", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_feed(principal: AuthorPrincipal, session: ScopedSession) -> None:
    """Revoke the caller's ICS subscription URL."""
    _require_household(principal)
    await service.revoke_feed(session, member_id=principal.user_id)


# --- External CalDAV subscriptions (P9-S2..S4) --------------------------------
# CRUD (9-S2) + the 15-min pull-sync (9-S3) + write-back (9-S4) + the connection probe; the web
# UI lives in web/src/calendar/subscriptions-section.tsx.
# Subscriptions are owner-only (service filters member_id → foreign = 404);
# credentials are write-only (the wire shape carries has_credentials, never the secret).


def _subscription_response(sub: ExternalCalendarSubscription) -> SubscriptionResponse:
    return SubscriptionResponse(
        id=sub.id,
        member_id=sub.member_id,
        label=sub.label,
        caldav_url=sub.caldav_url,
        enabled=sub.enabled,
        has_credentials=sub.creds_enc is not None,
        last_sync_at=sub.last_sync_at,
        last_sync_error=sub.last_sync_error,
    )


@calendar_router.get("/subscriptions")
async def list_subscriptions(
    principal: AuthorPrincipal, session: ScopedSession
) -> list[SubscriptionResponse]:
    """The caller's external CalDAV subscriptions (only their own — never a co-member's)."""
    _require_household(principal)
    subs = await service.list_subscriptions(session, member_id=principal.user_id)
    return [_subscription_response(sub) for sub in subs]


@calendar_router.post(
    "/subscriptions", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_subscription(
    payload: SubscriptionCreate,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> SubscriptionResponse:
    """Subscribe to an external CalDAV collection. With credentials the server crypto key is
    required (503 without one, ADR-0077); 409 on a duplicate URL."""
    household_id = _require_household(principal)
    sub = await service.create_subscription(
        session, household_id=household_id, member_id=principal.user_id, data=payload
    )
    response.headers["ETag"] = f'"{sub.version}"'
    return _subscription_response(sub)


@calendar_router.get("/subscriptions/{subscription_id}")
async def get_subscription(
    subscription_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> SubscriptionResponse:
    _require_household(principal)
    sub = await service.get_subscription(
        session, member_id=principal.user_id, subscription_id=subscription_id
    )
    response.headers["ETag"] = f'"{sub.version}"'
    return _subscription_response(sub)


@calendar_router.post(
    "/subscriptions/{subscription_id}/check", dependencies=[Depends(require_csrf)]
)
async def check_subscription(
    subscription_id: uuid.UUID,
    principal: AuthorPrincipal,
    session: ScopedSession,
    caldav: Annotated[CaldavPort, Depends(get_caldav)],
) -> SubscriptionCheckResponse:
    """Probe the stored URL + credentials once and answer immediately.

    Without it the only feedback on a wrong URL or password is ``last_sync_error`` after the next
    15-minute cron tick. A pure probe: nothing is written, no mirror is touched. A failure is
    answered as data (``ok=false`` + category), not raised — a typo is an expected outcome, not a
    server fault."""
    _require_household(principal)
    result = await service.check_subscription(
        session,
        caldav=caldav,
        member_id=principal.user_id,
        subscription_id=subscription_id,
    )
    return SubscriptionCheckResponse(ok=result.ok, category=result.category, objects=result.objects)


@calendar_router.patch("/subscriptions/{subscription_id}", dependencies=[Depends(require_csrf)])
async def update_subscription(
    subscription_id: uuid.UUID,
    payload: SubscriptionUpdate,
    request: Request,
    principal: AuthorPrincipal,
    session: ScopedSession,
    response: Response,
) -> SubscriptionResponse:
    """Patch a subscription under If-Match; new credentials replace the stored ones,
    ``clear_credentials`` drops them."""
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    sub = await service.update_subscription(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        subscription_id=subscription_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{sub.version}"'
    return _subscription_response(sub)


@calendar_router.delete(
    "/subscriptions/{subscription_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_subscription(
    subscription_id: uuid.UUID, principal: AuthorPrincipal, session: ScopedSession
) -> None:
    """Unsubscribe (soft-delete; the same URL can be re-subscribed afterwards)."""
    household_id = _require_household(principal)
    await service.delete_subscription(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        subscription_id=subscription_id,
    )


@calendar_router.get("/feed/{token}.ics", include_in_schema=False)
async def calendar_feed(token: str) -> Response:
    """Unauthenticated iCalendar feed (ADR-0042): a high-entropy token is the only credential — no
    cookies, calendar apps can't send them. Resolved cross-household via the maint session; events
    are then read under the owner's household scope. 404 on an unknown/revoked token."""
    async with maint_session() as msession:
        feed = await service.resolve_feed(msession, token=token)
    if feed is None:
        raise ProblemException(slug="not_found", title="Feed nicht gefunden", status=404)
    async with scoped_session(household_id=feed.household_id, user_id=feed.member_id) as session:
        events = await service.list_for_feed(session, viewer_id=feed.member_id)
    body = render_ics(events, name="Custode")
    return Response(content=body, media_type="text/calendar; charset=utf-8")
