from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class SyncClientOp(Base):
    """Idempotency log for the Sync-Batch (ARCHITECTURE §10): one row per applied client op so a
    replay is a no-op. Household-scoped (RLS); the reaper drops rows older than
    ``sync_ops_retention_days`` (default 30 — the docstring said 7 while the setting said 30,
    corrected 2026-07-31; the marker only has to outlive a client's retry window).
    Not a fact table — no version/tombstone, append-only."""

    __tablename__ = "sync_client_ops"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    client_op_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
