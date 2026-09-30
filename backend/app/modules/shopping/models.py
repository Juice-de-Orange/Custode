from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class ShoppingList(HouseholdScoped, Base):
    """A household shopping list (KONZEPT §5.5). RLS: household_id. Write path = Sync-Batch."""

    __tablename__ = "shopping_lists"

    name: Mapped[str] = mapped_column(String(100))
    category_order: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))


class ShoppingItem(HouseholdScoped, Base):
    """A shopping list item — an independent row; ``checked`` is its own field so checking never
    collides with renaming (LWW per field group, ADR-0032). RLS: household_id."""

    __tablename__ = "shopping_items"

    list_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shopping_lists.id"), index=True
    )
    label: Mapped[str] = mapped_column(String(200))
    qty: Mapped[str | None] = mapped_column(String(40))
    unit: Mapped[str | None] = mapped_column(String(40))
    category: Mapped[str | None] = mapped_column(String(100))
    checked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    checked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source: Mapped[str] = mapped_column(String(10), server_default=text("'manual'"))
    notes: Mapped[str | None] = mapped_column(Text)
    reserved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))


class ShoppingBasic(HouseholdScoped, Base):
    """A reusable staple the household curates — a template for 1-tap add (T4). RLS: household_id.
    Write path = Sync-Batch (a third sync entity of the module)."""

    __tablename__ = "shopping_basics"

    label: Mapped[str] = mapped_column(String(200))
    category: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
