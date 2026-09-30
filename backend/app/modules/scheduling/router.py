"""HTTP layer for ``scheduling`` (KONZEPT §5.12). Read-only slot suggestions for the calling member;
the user opts in by creating a calendar event from a returned slot. member/admin."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Query

from app.kernel.auth.context import Principal
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession
from app.kernel.http.problem import ProblemException
from app.modules.scheduling import service
from app.modules.scheduling.schemas import SlotResponse

scheduling_router = APIRouter(prefix="/v1/scheduling", tags=["scheduling"])

_DEFAULT_HORIZON = timedelta(days=7)
_MAX_HORIZON = timedelta(days=31)


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


@scheduling_router.get("/slots")
async def suggest_slots(
    principal: CurrentPrincipal,
    session: ScopedSession,
    duration_min: Annotated[int, Query(ge=5, le=24 * 60)] = 60,
    frm: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    day_start: Annotated[int, Query(ge=0, le=23)] = service.DEFAULT_DAY_START_HOUR,
    day_end: Annotated[int, Query(ge=1, le=24)] = service.DEFAULT_DAY_END_HOUR,
    limit: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[SlotResponse]:
    """Suggest up to ``limit`` conflict-free slots of ``duration_min`` minutes within the window
    (defaults: now .. now+7 days) and the daily working hours ``[day_start, day_end]`` (UTC)."""
    _require_household(principal)
    window_from = frm if frm is not None else datetime.now(UTC)
    window_to = to if to is not None else window_from + _DEFAULT_HORIZON
    if window_to <= window_from:
        raise ProblemException(slug="invalid_range", title="Ungültiges Zeitfenster", status=422)
    if window_to - window_from > _MAX_HORIZON:
        window_to = window_from + _MAX_HORIZON
    if day_end <= day_start:
        raise ProblemException(slug="invalid_hours", title="Ungültige Arbeitszeiten", status=422)
    slots = await service.suggest_slots(
        session,
        viewer_id=principal.user_id,
        frm=window_from,
        to=window_to,
        duration=timedelta(minutes=duration_min),
        day_start_hour=day_start,
        day_end_hour=day_end,
        max_results=limit,
    )
    return [SlotResponse(start=s.start, end=s.end, reasons=s.reasons) for s in slots]
