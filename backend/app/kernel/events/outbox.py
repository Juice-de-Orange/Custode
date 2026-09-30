"""Outbox, processed-events and dead-letter tables (ARCHITECTURE §8.2).

The outbox row is written in the SAME transaction as the fact change, so a crash
never loses an event. The durable dispatcher (Phase 1 worker) polls undispatched
rows, runs each registered handler, and records ``(handler, event_id)`` in
``processed_events`` for idempotency (at-least-once delivery + idempotent handlers
= effectively once). After a bounded number of failures an event is copied to
``events_dlq`` and an alert is raised.

``events_outbox``/``events_dlq`` carry ``household_id`` and are RLS-protected like
any fact table — the write path (``custode_app``) appends within the active
household. ``processed_events`` is an internal ledger without tenant data.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class OutboxEvent(Base):
    """A domain event awaiting (or past) dispatch. Identity/payload are immutable;
    the dispatch state (``attempts``/``next_attempt_at``/``processed_at``) is
    updated by the dispatcher."""

    __tablename__ = "events_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    type: Mapped[str] = mapped_column(String(100), index=True)
    version: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # NULL until every registered handler has run; set by the dispatcher.
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class ProcessedEvent(Base):
    """Idempotency ledger: ``(handler, event_id)`` marks a handler as having run."""

    __tablename__ = "processed_events"

    handler: Mapped[str] = mapped_column(String(200), primary_key=True)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class DeadLetterEvent(Base):
    """An event that exhausted its retries — retained for inspection and replay."""

    __tablename__ = "events_dlq"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    type: Mapped[str] = mapped_column(String(100))
    household_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    attempts: Mapped[int] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
