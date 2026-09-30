from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class Recipe(HouseholdScoped, Base):
    """A household recipe (KONZEPT §5.2). RLS: household_id = app.household_id. ``version`` (from
    the mixin, bumped by the shared trigger) is the ETag for PATCH + If-Match."""

    __tablename__ = "recipes"

    title: Mapped[str] = mapped_column(String(200))
    servings: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    steps_md: Mapped[str] = mapped_column(Text, server_default=text("''"))
    prep_minutes: Mapped[int | None] = mapped_column(Integer)
    cook_minutes: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    source_url: Mapped[str | None] = mapped_column(Text)
    photo_key: Mapped[str | None] = mapped_column(String(80))  # blob-storage key; None = no photo
    # "Last cooked" history, fed by the mealplanner (mealplan.cooked, P6-S3). Foundation for the
    # automation's repeat-lockout ("don't suggest within X days").
    last_cooked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooked_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class RecipeIngredient(HouseholdScoped, Base):
    """One ingredient line of a recipe. ``raw_text`` is always preserved (the canonical-ingredient
    mapping is reversible; ``ingredient_id`` is NULL until mapped in S4). RLS: household_id."""

    __tablename__ = "recipe_ingredients"

    recipe_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("recipes.id"), index=True
    )
    raw_text: Mapped[str] = mapped_column(Text)
    qty: Mapped[str | None] = mapped_column(String(40))
    unit: Mapped[str | None] = mapped_column(String(40))
    ingredient_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
