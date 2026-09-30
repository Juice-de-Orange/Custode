"""HTTP contracts for ``mealplanner`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, model_validator

MealSlotKey = Literal["breakfast", "lunch", "dinner", "snack"]


class SlotSet(BaseModel):
    """Set one slot of the week. A slot is a recipe **or** free text (not both); both null clears
    the content but may still carry a cook/note. ``cook_id`` is who cooks (optional)."""

    day_of_week: int = Field(ge=0, le=6)
    slot: MealSlotKey
    recipe_id: uuid.UUID | None = None
    free_text: str | None = Field(default=None, max_length=200)
    cook_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _recipe_xor_text(self) -> SlotSet:
        if self.recipe_id is not None and self.free_text:
            raise ValueError("a slot is a recipe or free text, not both")
        return self


class MealSlotResponse(BaseModel):
    """One filled slot. ``recipe_title`` is resolved via recipes.api (null if the recipe was since
    deleted or the slot is free text)."""

    day_of_week: int
    slot: MealSlotKey
    recipe_id: uuid.UUID | None
    recipe_title: str | None
    free_text: str | None
    cook_id: uuid.UUID | None
    note: str | None


class WeekResponse(BaseModel):
    """A week's plan: its Monday plus every filled slot (empty slots are simply absent).
    ``absent_days`` = weekday indices (0-6) the viewer is away (Synergie S-01, ADR-0054); only the
    read endpoint fills it (writes return ``[]`` — the web refetches the week after a mutation)."""

    week_start: date
    slots: list[MealSlotResponse]
    absent_days: list[int] = Field(default_factory=list)


class GenerateResult(BaseModel):
    """How many distinct shopping items the week's recipes added to the default list (S-?? §5.5)."""

    added: int


class CookTaskResult(BaseModel):
    """The personal cooking task created from a slot (Synergie S-03, ADR-0053)."""

    title: str
    assigned_to: uuid.UUID


class WeekNutrition(BaseModel):
    """Summed per-portion macros of the week's planned recipes (P6-S10). ``meals_counted`` = how
    many recipe-slots contributed; ``confidence`` is ``estimated`` if any recipe lacked data."""

    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    meals_counted: int
    confidence: str
    # Optional ±10% goal evaluation (P6-S11): set only when ``target_kcal`` was passed and a recipe
    # was counted. ``verdict`` in {under, on_target, over}; compares the per-portion average kcal.
    target_kcal: float | None = None
    verdict: str | None = None


class PrepTaskResult(BaseModel):
    """The advance-prep task created from a slot (Synergie S-02, ADR-0055). ``hint`` is the matched
    lead-time cue (e.g. ``"marinieren"``) that triggered it."""

    title: str
    assigned_to: uuid.UUID
    hint: str


class PersonalSuggestionResponse(BaseModel):
    """A recipe proposed TO the caller — never written to the shared week plan.

    ``reasons`` are machine-readable codes the web translates (mirroring the scheduling engine).
    Because this endpoint writes nothing, the caller's own recovery signal may shape it without a
    health state ever determining a household record (ADR-0081 §9)."""

    recipe_id: uuid.UUID
    title: str
    total_minutes: int | None = None
    reasons: list[str] = []
