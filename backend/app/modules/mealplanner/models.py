from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, SmallInteger, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.kernel.db.base import Base, HouseholdScoped


class MealPlan(HouseholdScoped, Base):
    """One week of meal planning for a household (KONZEPT §5.4). ``week_start`` is the Monday of the
    ISO week; one plan per household per week (unique index in the migration). RLS: household_id."""

    __tablename__ = "meal_plans"

    week_start: Mapped[date] = mapped_column(Date)


class MealSlot(HouseholdScoped, Base):
    """One cell of the week grid — a ``day_of_week`` (0=Mon..6=Sun) by ``slot`` (breakfast/lunch/
    dinner/snack). Holds either a ``recipe_id`` (resolved to a title via recipes.api — no DB FK, so
    a deleted recipe just dangles to None) **or** a ``free_text`` entry ("leftovers", "eating out"),
    plus ``cook_id`` (who cooks). Unique per (plan, day, slot). RLS: household_id."""

    __tablename__ = "meal_slots"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("meal_plans.id", ondelete="CASCADE"), index=True
    )
    day_of_week: Mapped[int] = mapped_column(SmallInteger)
    slot: Mapped[str] = mapped_column(String(12))  # breakfast | lunch | dinner | snack (CHECK)
    recipe_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    free_text: Mapped[str | None] = mapped_column(String(200))
    cook_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    note: Mapped[str | None] = mapped_column(String(200))
