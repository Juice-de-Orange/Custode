"""scheduling use-cases (KONZEPT §5.12). Reads the calendar occupancy seam (calendar.api) under the
request's RLS-scoped session and runs the pure engine. No tables of its own yet; suggestions are
read-only (the user opts in by creating a calendar event from a slot)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.calendar import api as calendar_api
from app.modules.scheduling.engine import FreeSlot, find_free_slots
from app.modules.wearables import api as wearables_api
from app.modules.weather import api as weather_api

DEFAULT_DAY_START_HOUR = 7
DEFAULT_DAY_END_HOUR = 21


async def suggest_slots(
    session: AsyncSession,
    *,
    viewer_id: uuid.UUID,
    frm: datetime,
    to: datetime,
    duration: timedelta,
    day_start_hour: int = DEFAULT_DAY_START_HOUR,
    day_end_hour: int = DEFAULT_DAY_END_HOUR,
    max_results: int = 5,
) -> list[FreeSlot]:
    """Suggest conflict-free slots for the viewer within ``[frm, to]``. Occupied intervals come from
    the viewer's ``busy`` calendar events plus their own ``absence`` periods (calendar.api, RLS +
    layer-visibility honoured); the household weather forecast (weather.api, optional) tags rainy
    days, and the viewer's OWN wearable reading (wearables.api, optional) tags a day they are run
    down (Synergie S-14). The pure engine then carves out the free slots."""
    busy = await calendar_api.list_busy_intervals(session, viewer_id=viewer_id, frm=frm, to=to)
    absences = await calendar_api.list_absence_intervals(
        session, viewer_id=viewer_id, frm=frm, to=to
    )
    rain_by_date = await _rain_by_date(session)
    low_recovery_dates = await _low_recovery_dates(session, viewer_id=viewer_id, frm=frm)
    return find_free_slots(
        busy,
        frm=frm,
        to=to,
        duration=duration,
        day_start_hour=day_start_hour,
        day_end_hour=day_end_hour,
        max_results=max_results,
        absences=absences,
        rain_by_date=rain_by_date,
        low_recovery_dates=low_recovery_dates,
    )


async def _low_recovery_dates(
    session: AsyncSession, *, viewer_id: uuid.UUID, frm: datetime
) -> set[str]:
    """The days to flag for Synergie S-14, from the VIEWER's own wearable reading.

    ``member_id=viewer_id`` is the whole privacy story: the signal shapes only the suggestions
    this member receives, and the member-scoped RLS would return nothing for anybody else anyway
    (N-2, ADR-0081).

    Only **today** can be flagged. A reading describes the past; nothing measured this morning
    says anything about next Thursday, so claiming a whole week would be a lie dressed as a
    feature. Empty set = base path (no connection, no consent, stale reading, wearables off) —
    the engine then adds no hint at all, exactly like a household without wearables."""
    today = frm.date()
    signal = await wearables_api.recovery_signal(session, member_id=viewer_id, today=today)
    return {today.isoformat()} if signal.available and signal.low_recovery else set()


async def _rain_by_date(session: AsyncSession) -> dict[str, int]:
    """Map each forecast day to its max precipitation probability (%). Empty if weather is off /
    unconfigured / upstream down — the engine then simply adds no rain warnings (graceful)."""
    forecast = await weather_api.get_forecast(session)
    if forecast is None:
        return {}
    return {
        day.date: day.precipitation_probability_max
        for day in forecast.daily
        if day.precipitation_probability_max is not None
    }
