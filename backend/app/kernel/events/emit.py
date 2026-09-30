"""Transactional outbox emit (ARCHITECTURE §8.2).

A feature module calls :func:`emit` to append a domain event to the SAME session (and
thus the same transaction) as the fact change. Because the event row commits or rolls
back atomically with the change, an event can never be lost on a crash nor leak from a
rolled-back change. The durable dispatcher (worker) delivers it afterwards.

``id``/``occurred_at`` default in the DB (``uuidv7()`` / ``now()``). The row is written
under ``custode_app``, so ``household_id`` MUST equal the session's active scope or the
RLS WITH CHECK on ``events_outbox`` rejects it — callers pass the scope they already hold.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.outbox import OutboxEvent


async def emit(
    session: AsyncSession,
    *,
    type: str,
    household_id: uuid.UUID,
    payload: dict[str, Any],
    version: int = 1,
) -> None:
    """Append a domain event to ``events_outbox`` within the caller's transaction. No
    flush/commit — the event commits with the surrounding unit of work."""
    session.add(OutboxEvent(type=type, household_id=household_id, payload=payload, version=version))
