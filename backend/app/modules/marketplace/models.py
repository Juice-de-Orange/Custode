from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Integer, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class MarketListing(HouseholdScoped, Base):
    """A task instance put up for sale (KONZEPT §5.10). RLS: household_id. The price is reserved
    into ``escrow:<listing_id>`` (economy ledger) at listing time — never a stored balance.

    Status machine: ``open -> accepted -> settled`` (Käufer erledigt die Task), oder ``open ->
    withdrawn`` (Verkäufer zieht zurück, Escrow zurück), oder ``accepted -> reverted`` (Verfall →
    Rückfall, S8b). ``task_instance_id`` ist eine reine ID (kein Cross-Modul-FK — Validierung läuft
    über ``tasks.api``); ``seller_id``/``buyer_id`` sind user_ids."""

    __tablename__ = "market_listings"

    task_instance_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    title: Mapped[str] = mapped_column(String(200))  # snapshot of the task title at listing time
    seller_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    price: Mapped[int] = mapped_column(Integer)  # CHECK (price > 0) in migration
    # open | accepted | settled | reverted | withdrawn (CHECK constraint in migration)
    status: Mapped[str] = mapped_column(String(10), server_default="open")
    buyer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class AutoAcceptRule(HouseholdScoped, Base):
    """A member's standing rule to auto-accept matching listings (KONZEPT §5.10, Audit A-05). RLS:
    household_id. ``template_id`` NULL = any task type; the rule fires when a new listing's task
    template matches and its price <= ``max_price``. Among several matching members, the fairness
    account decides (lowest load wins)."""

    __tablename__ = "auto_accept_rules"

    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # NULL = any
    max_price: Mapped[int] = mapped_column(Integer)  # CHECK (> 0) in migration
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
