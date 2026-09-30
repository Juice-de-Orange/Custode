"""HTTP request/response contracts for ``recipes`` (single source for the OpenAPI schema → web zod
client). Separate from the ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class IngredientLine(BaseModel):
    raw_text: str = Field(min_length=1, max_length=500)
    qty: str | None = Field(default=None, max_length=40)
    unit: str | None = Field(default=None, max_length=40)


class RecipeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    servings: int = Field(default=1, ge=1, le=100)
    steps_md: str = Field(default="", max_length=20000)
    prep_minutes: int | None = Field(default=None, ge=0, le=100000)
    cook_minutes: int | None = Field(default=None, ge=0, le=100000)
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = Field(default=None, max_length=2000)
    ingredients: list[IngredientLine] = Field(default_factory=list)


class RecipeUpdate(BaseModel):
    """Partial update (If-Match). ``ingredients``, if provided, replaces the whole list."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    servings: int | None = Field(default=None, ge=1, le=100)
    steps_md: str | None = Field(default=None, max_length=20000)
    prep_minutes: int | None = Field(default=None, ge=0, le=100000)
    cook_minutes: int | None = Field(default=None, ge=0, le=100000)
    tags: list[str] | None = None
    source_url: str | None = Field(default=None, max_length=2000)
    ingredients: list[IngredientLine] | None = None


class IngredientResponse(BaseModel):
    raw_text: str
    qty: str | None
    unit: str | None
    ingredient_id: uuid.UUID | None
    ingredient_name: str | None  # canonical match (S4b); None if unmapped


class RecipeResponse(BaseModel):
    """Full recipe; ``version`` is the ETag for If-Match optimistic concurrency."""

    id: uuid.UUID
    title: str
    servings: int
    steps_md: str
    prep_minutes: int | None
    cook_minutes: int | None
    tags: list[str]
    source_url: str | None
    ingredients: list[IngredientResponse]
    version: int
    has_photo: bool
    last_cooked_at: datetime | None


class RecipeSummary(BaseModel):
    """Lightweight list-card view."""

    id: uuid.UUID
    title: str
    servings: int
    tags: list[str]
    has_photo: bool
    last_cooked_at: datetime | None


class RecipeImportRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2000)


class RecipeImportResponse(BaseModel):
    """A review-before-save draft extracted from a URL (KONZEPT §5.2). Same shape the editor
    pre-fills; the user confirms/corrects, then saves via ``POST /v1/recipes``. Not persisted."""

    title: str
    servings: int
    steps_md: str
    tags: list[str]
    source_url: str
    ingredients: list[IngredientLine]


class NutritionOut(BaseModel):
    """Per-portion nutrition for a recipe (computed via nutrition.api; S5). ``confidence`` is
    ``"complete"`` only if every line was counted, else ``"estimated"``; ``covered``/``total`` =
    how many lines contributed."""

    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    sugar_g: float
    fiber_g: float
    confidence: str
    covered: int
    total: int
