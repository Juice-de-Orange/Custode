"""Retention reaper for the Sync-Batch idempotency log (``sync_client_ops``, ARCHITECTURE §8.4/§10).
Runs as ``custode_maint`` (spans households) on the scheduler's hourly cron. Re-applying an op after
its marker is reaped is safe under LWW — a field-merge upsert is mostly a no-op — so a generous
retention is fine; the markers only exist to collapse near-term replays into no-ops."""

from __future__ import annotations

from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

_REAP_SYNC_OPS = text(
    "DELETE FROM sync_client_ops WHERE created_at < now() - make_interval(days => :days)"
)


async def reap_sync_ops(session: AsyncSession, *, retention_days: int) -> int:
    """Delete idempotency markers older than ``retention_days``; returns how many were removed."""
    result = cast(
        CursorResult[Any], await session.execute(_REAP_SYNC_OPS, {"days": retention_days})
    )
    await session.commit()
    return result.rowcount
