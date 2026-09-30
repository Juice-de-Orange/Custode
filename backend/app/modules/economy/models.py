from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class LedgerEntry(HouseholdScoped, Base):
    """One movement in the household's append-only double-entry points ledger (KONZEPT §5.9,
    ADR-0035). RLS: household_id = app.household_id.

    A movement is a single row ``from_account -> to_account`` with ``amount > 0``. Accounts are
    strings: ``system`` (mint/sink), ``member:<uuid>``, ``escrow:<listing_id>``. A balance is a SUM
    (``sum(to) - sum(from)``), never a stored field. Rows are append-only (never edited or deleted);
    a correction is a new counter-entry (``ref_type='admin_correction'``). The mixin's
    ``version``/``updated_at``/``deleted_at`` therefore stay at their defaults (the update trigger
    never fires).

    Append-only governs **corrections inside a living ledger**: deleting one movement would shift
    the balances of the *other* account. It is not a promise that rows outlive the tenant — the
    household purge (11-S1f, ADR-0086 §6) empties this table when the household is dissolved, and
    there are no other balances left to keep consistent. The member exit (11-S1b) is the opposite
    case and stays a *booking* (``ref_type='member_exit'``), precisely because the others remain."""

    __tablename__ = "points_ledger"

    from_account: Mapped[str] = mapped_column(String(80))
    to_account: Mapped[str] = mapped_column(String(80))
    amount: Mapped[int] = mapped_column(Integer)  # CHECK (amount > 0) in migration
    ref_type: Mapped[str] = mapped_column(String(40))  # task_completion | admin_correction | …
    ref_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class Reward(HouseholdScoped, Base):
    """An admin-defined real-world reward redeemable for points (KONZEPT §5.9). RLS: household_id.
    ``version`` is the ETag for admin PATCH + If-Match. ``stock`` NULL = unlimited;
    ``cooldown_hours`` NULL = no cooldown. ``kind``: standard | mealplan_wish | custom."""

    __tablename__ = "rewards"

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    cost: Mapped[int] = mapped_column(Integer)  # CHECK (cost > 0) in migration
    stock: Mapped[int | None] = mapped_column(Integer)  # remaining quota; NULL = unlimited
    cooldown_hours: Mapped[int | None] = mapped_column(Integer)  # per-member cooldown; NULL = none
    kind: Mapped[str] = mapped_column(String(20), server_default=text("'standard'"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class Redemption(HouseholdScoped, Base):
    """A member's redemption of a reward (KONZEPT §5.9). RLS: household_id. The points are debited
    (member -> system) at redeem time; ``status`` tracks the real-world fulfilment by the admin.
    Never hard-deleted **as an operation** (history); a redemption is a state machine
    ``requested -> fulfilled``. It does fall with the tenant: the household purge empties this
    table on dissolution (11-S1f, ADR-0086)."""

    __tablename__ = "redemptions"

    reward_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rewards.id"), index=True
    )
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(200))  # snapshot of the reward title at redeem time
    cost: Mapped[int] = mapped_column(Integer)  # snapshot of the cost paid
    status: Mapped[str] = mapped_column(String(10), server_default=text("'requested'"))
