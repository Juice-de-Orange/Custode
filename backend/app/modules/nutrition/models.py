from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base


class Ingredient(Base):
    """Canonical ingredient — GLOBAL reference data, no ``household_id`` (ADR-0031); the same corpus
    for every household. Read-only for the app role; curated via migrations. ``grams_per_unit`` maps
    a unit label to grams (nutrition + scaling, S5); ``aliases`` aid free-text matching."""

    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    name_de: Mapped[str] = mapped_column(String(120))
    name_en: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(60))
    default_unit: Mapped[str] = mapped_column(String(20))
    grams_per_unit: Mapped[dict[str, float]] = mapped_column(JSONB, server_default=text("'{}'"))
    aliases: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngredientNutrition(Base):
    """Per-100g nutrition for a canonical ingredient — GLOBAL reference data (ADR-0031). Read-only,
    curated via migrations (``manual`` now, USDA/Open Food Facts later). One row per ingredient."""

    __tablename__ = "ingredient_nutrition"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuidv7()")
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingredients.id"), unique=True
    )
    source: Mapped[str] = mapped_column(String(20), server_default=text("'manual'"))
    kcal: Mapped[float] = mapped_column(Float)
    protein_g: Mapped[float] = mapped_column(Float)
    fat_g: Mapped[float] = mapped_column(Float)
    carbs_g: Mapped[float] = mapped_column(Float)
    sugar_g: Mapped[float] = mapped_column(Float)
    fiber_g: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
