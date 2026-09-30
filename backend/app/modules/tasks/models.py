from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class TaskTemplate(HouseholdScoped, Base):
    """A reusable household-task definition (KONZEPT §5.9). RLS: household_id = app.household_id.
    ``version`` (from the mixin, bumped by the shared trigger) is the ETag for PATCH + If-Match.

    ``points`` is an inert column in P4-S1 (a default value the admin sets per template) — it is
    NEVER booked into a ledger here; the points economy lands in a later slice (ADR-0034). Deferred
    columns (``rrule``, ``pool``, ``room_id``) are added additively in their consumer slice."""

    __tablename__ = "task_templates"

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    points: Mapped[int] = mapped_column(
        Integer, server_default=text("0")
    )  # CHECK (>= 0) in migration
    duration_est_minutes: Mapped[int | None] = mapped_column(Integer)
    outdoor: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    # fair | fixed | open — stored only in S1, not enforced (CHECK constraint in migration).
    rotation: Mapped[str] = mapped_column(String(10), server_default=text("'open'"))
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # optional room (S6)


class TaskInstance(HouseholdScoped, Base):
    """A concrete occurrence of a task (KONZEPT §5.9). RLS: household_id. Lifecycle is a state
    machine (``open -> done`` in S1; ``expired`` reserved for a later worker) — never hard-deleted.
    ``title``/``points`` are snapshotted at creation (a later template edit must not rewrite the
    history, and the eventual ledger books a stable value). ``done_by``/``done_at`` are server-set
    on completion (not client-writable). ``version`` is the ETag for completion's If-Match."""

    __tablename__ = "task_instances"

    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_templates.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    points: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # a member's user_id
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # open | done | expired | armed (CHECK in migration). ``armed`` = an action-chain follow-up
    # (KONZEPT §5.17), not yet actionable; a matching ``shopping.item.checked`` flips it to ``open``
    # (capture handler). Armed tasks are excluded from the default open list.
    status: Mapped[str] = mapped_column(String(8), server_default=text("'open'"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    done_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    # Optional direct room (P5-S11, S-13): lets an ad-hoc instance (no template) belong to a room.
    # The heatmap's effective room is COALESCE(instance.room_id, template.room_id).
    room_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    # the effective (possibly decayed) points credited at completion; NULL until done (KONZEPT §5.9)
    awarded_points: Mapped[int | None] = mapped_column(Integer)
    # action-chain activation condition, e.g. {"on_item_checked": "<shopping_item_id>"} (KONZEPT
    # §5.17); NULL for a normal task. Set when a Zuruf arms a follow-up; read by capture's handler.
    activation_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class Room(HouseholdScoped, Base):
    """A household room/zone (KONZEPT §5.9/§5.8). RLS: household_id. ``decay_days`` defines the
    freshness window for the computed heatmap (green/amber/red = f(last completion, decay_days));
    the heatmap status itself is never stored. ``version`` is the ETag for admin If-Match."""

    __tablename__ = "rooms"

    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[str | None] = mapped_column(String(40))
    decay_days: Mapped[int] = mapped_column(Integer)  # CHECK (> 0) in migration
