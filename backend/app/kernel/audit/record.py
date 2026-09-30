"""Write helper for the append-only audit log (ADR-0073). Call from operator actions (and later
security events) on an ``ops_actions`` session. Append-only: this only ever INSERTs."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.audit.model import AuditEntry


async def record_audit(
    session: AsyncSession,
    *,
    actor_type: str,
    action: str,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    household_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEntry:
    """Append one audit record. ``detail`` is structured context but must contain **no PII**
    (caller's responsibility). The session must be committed by the caller's unit of work."""
    entry = AuditEntry(
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        household_id=household_id,
        detail_json=detail or {},
        request_id=request_id,
    )
    session.add(entry)
    await session.flush()
    return entry
