"""The one signal wearables hands to other modules (P9-S7, Synergie S-14).

KONZEPT §9 S-14: „Wearable-Schonung: XL-Tasks meiden Erschöpfungstage — **ausschließlich auf
Basis der eigenen Daten, nur für eigene Vorschläge**." Both halves of that sentence are load-
bearing, and they shape this module:

* **Only your own data.** ``recovery_signal`` takes a ``member_id`` and is only ever called with
  the requesting member's own id — the member-scoped RLS (migration 0069) makes any other value
  return nothing anyway, so the guarantee is enforced, not promised.
* **Only your own suggestions.** Consumers may use this to shape what they OFFER the member. The
  result must never be rendered, aggregated, or otherwise made visible to anyone else; a
  co-member must not be able to infer it from what they see.

**A deliberately narrow interface.** Wearable data describes the PAST; scheduling and meal
planning are about the FUTURE. Nothing measured today says anything about next Thursday, so this
returns exactly one honest statement — "the most recent reading says this person is currently run
down" — and never a per-future-day forecast. Consumers apply it to today, not to a week.

Boolean, not a score: a raw readiness number leaking into another module's response would be the
health value itself. A single yes/no carries what a suggestion needs and nothing more.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.wearables.models import WearableDailyRow

#: Below this, Oura-style 0-100 scores mean "poor" rather than "pay attention" (their own bands
#: put 70-84 at "good" and below 70 at "pay attention"). We deliberately sit at the lower,
#: unambiguous end: a nudge that fires on a merely mediocre night would be noise, and this
#: feature has to earn its interruption.
LOW_SCORE_THRESHOLD = 60

#: How stale a reading may be and still describe "now". A value from four days ago says nothing
#: about today; treating it as current would be worse than having no signal at all.
MAX_READING_AGE_DAYS = 1


@dataclass(frozen=True)
class RecoverySignal:
    """What another module is allowed to know. ``available=False`` is the base path — no
    connection, no consent, no recent reading, or the feature switched off — and every consumer
    must behave exactly as it does today when it sees it."""

    available: bool = False
    low_recovery: bool = False
    #: Which day the reading describes. Useful for a "as of yesterday" hint; never a value.
    as_of: date | None = None


NO_SIGNAL = RecoverySignal()


def evaluate(
    *, readiness: int | None, sleep_score: int | None, day: date, today: date
) -> RecoverySignal:
    """Pure decision rule, separated from the query so it is testable without a database.

    Low recovery = the most recent reading has a readiness OR sleep score below the threshold.
    Either one alone is enough: a bad night and a bad readiness both mean "go easy today", and
    requiring both would silence the signal for anyone who consented to only one data type."""
    if day < today - timedelta(days=MAX_READING_AGE_DAYS):
        return NO_SIGNAL
    scores = [s for s in (readiness, sleep_score) if s is not None]
    if not scores:
        return NO_SIGNAL
    return RecoverySignal(
        available=True,
        low_recovery=min(scores) < LOW_SCORE_THRESHOLD,
        as_of=day,
    )


async def recovery_signal(
    session: AsyncSession, *, member_id: uuid.UUID, today: date
) -> RecoverySignal:
    """The member's own recovery state from their most recent reading.

    Reads under the caller's already-scoped session, so the member-scoped RLS applies: asking for
    somebody else's ``member_id`` yields no rows and therefore ``NO_SIGNAL``. Every failure mode
    — no connection, consent withdrawn (the columns are NULL), stale data, wearables off — lands
    on the same neutral answer, so consumers need exactly one base path, not five."""
    row = (
        await session.execute(
            select(
                WearableDailyRow.day,
                WearableDailyRow.readiness,
                WearableDailyRow.sleep_score,
            )
            .where(WearableDailyRow.member_id == member_id)
            .order_by(WearableDailyRow.day.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return NO_SIGNAL
    return evaluate(readiness=row.readiness, sleep_score=row.sleep_score, day=row.day, today=today)
