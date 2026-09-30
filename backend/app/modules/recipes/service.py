"""recipes use-cases. Services own no transaction control here — they run on the request's
RLS-scoped session (``household_id = app.household_id``); the dependency commits the unit of work.
Recipes use PATCH + If-Match (ADR-0029): ``version`` is the ETag, bumped by the shared trigger."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.events.emit import emit
from app.kernel.fetch import safe_fetch
from app.kernel.http.problem import ProblemException
from app.kernel.storage import get_storage
from app.modules.nutrition import api as nutrition_api
from app.modules.recipes.importer import extract_jsonld_recipe, extract_with_scrapers
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.schemas import (
    IngredientLine,
    RecipeCreate,
    RecipeImportResponse,
    RecipeUpdate,
)


async def _add_ingredients(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
    lines: list[IngredientLine],
) -> None:
    # Best-effort auto-map each line to a canonical ingredient (nutrition's public api, ADR-0031).
    # Candidates load once; raw_text stays the source of truth, the match is only a suggestion.
    candidates = await nutrition_api.load_candidates(session) if lines else []
    for position, line in enumerate(lines):
        match = nutrition_api.best_match(candidates, line.raw_text)
        session.add(
            RecipeIngredient(
                household_id=household_id,
                recipe_id=recipe_id,
                raw_text=line.raw_text,
                qty=line.qty,
                unit=line.unit,
                ingredient_id=match.id if match else None,
                position=position,
            )
        )


async def create_recipe(
    session: AsyncSession, *, household_id: uuid.UUID, data: RecipeCreate
) -> Recipe:
    """Create a recipe + its ingredient lines (in one tx). Emits ``recipe.created``."""
    recipe = Recipe(
        household_id=household_id,
        title=data.title,
        servings=data.servings,
        steps_md=data.steps_md,
        prep_minutes=data.prep_minutes,
        cook_minutes=data.cook_minutes,
        tags=list(data.tags),
        source_url=data.source_url,
    )
    session.add(recipe)
    await session.flush()  # recipe must exist before its ingredient FKs (BUGLOG 2026-06-19)
    await _add_ingredients(
        session, household_id=household_id, recipe_id=recipe.id, lines=data.ingredients
    )
    await emit(
        session,
        type="recipe.created",
        household_id=household_id,
        payload={"recipe_id": str(recipe.id)},
    )
    await session.flush()
    return recipe


async def list_recipes(session: AsyncSession) -> list[Recipe]:
    """The active household's recipes (RLS-scoped). Soft-deleted rows excluded."""
    rows = await session.scalars(
        select(Recipe).where(Recipe.deleted_at.is_(None)).order_by(Recipe.title)
    )
    return list(rows)


async def get_recipe(session: AsyncSession, *, recipe_id: uuid.UUID) -> Recipe:
    """One recipe of the active household (RLS hides other households -> 404)."""
    recipe = await session.get(Recipe, recipe_id)
    if recipe is None or recipe.deleted_at is not None:
        raise ProblemException(slug="not_found", title="Rezept nicht gefunden", status=404)
    return recipe


async def mark_cooked(
    session: AsyncSession, *, household_id: uuid.UUID, recipe_id: uuid.UUID, when: datetime
) -> Recipe:
    """Record that a recipe was cooked: bump ``last_cooked_at`` + ``cooked_count`` (KONZEPT §5.2).
    The one-way seam the mealplanner calls on ``mealplan.cooked``; emits ``recipe.updated`` so the
    list refreshes. 404 if the recipe is gone (RLS/deleted)."""
    recipe = await get_recipe(session, recipe_id=recipe_id)
    recipe.last_cooked_at = when
    recipe.cooked_count = (recipe.cooked_count or 0) + 1
    await emit(session, type="recipe.updated", household_id=household_id, payload={})
    await session.flush()
    return recipe


async def get_ingredients(session: AsyncSession, *, recipe_id: uuid.UUID) -> list[RecipeIngredient]:
    rows = await session.scalars(
        select(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe_id, RecipeIngredient.deleted_at.is_(None))
        .order_by(RecipeIngredient.position)
    )
    return list(rows)


@dataclass(frozen=True)
class RecipeMacros:
    """Per-portion macros of a recipe (Synergie-Naht für den Mealplanner, P6-S10). A plain,
    recipes-owned value object so callers need not import nutrition's ``NutritionResult``."""

    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    confidence: str  # "complete" if every ingredient line counted, else "estimated"


async def recipe_macros(session: AsyncSession, *, recipe_id: uuid.UUID) -> RecipeMacros | None:
    """Per-portion macros for a recipe via ``nutrition.api`` (same compute as the recipe nutrition
    endpoint). ``None`` if the recipe is gone (soft-deleted/other household). Cross-module seam: the
    mealplanner aggregates these for the week without importing ``nutrition``."""
    recipe = await session.get(Recipe, recipe_id)
    if recipe is None or recipe.deleted_at is not None:
        return None
    ingredients = await get_ingredients(session, recipe_id=recipe_id)
    result = await nutrition_api.calculate(
        session,
        lines=[(i.raw_text, i.ingredient_id) for i in ingredients],
        servings=recipe.servings,
    )
    return RecipeMacros(
        kcal=result.kcal,
        protein_g=result.protein_g,
        fat_g=result.fat_g,
        carbs_g=result.carbs_g,
        confidence=result.confidence,
    )


async def update_recipe(
    session: AsyncSession,
    *,
    household_id: uuid.UUID,
    recipe_id: uuid.UUID,
    expected_version: int,
    data: RecipeUpdate,
) -> Recipe:
    """Patch a recipe under optimistic concurrency (``expected_version`` = If-Match). Replacing
    ``ingredients`` replaces all lines (soft-delete + re-add). Emits ``recipe.updated``."""
    recipe = await get_recipe(session, recipe_id=recipe_id)
    if recipe.version != expected_version:
        raise ProblemException(
            slug="precondition_failed", title="Rezept zwischenzeitlich geändert", status=412
        )
    if data.title is not None:
        recipe.title = data.title
    if data.servings is not None:
        recipe.servings = data.servings
    if data.steps_md is not None:
        recipe.steps_md = data.steps_md
    if data.prep_minutes is not None:
        recipe.prep_minutes = data.prep_minutes
    if data.cook_minutes is not None:
        recipe.cook_minutes = data.cook_minutes
    if data.tags is not None:
        recipe.tags = list(data.tags)
    if data.source_url is not None:
        recipe.source_url = data.source_url
    if data.ingredients is not None:
        await session.execute(
            update(RecipeIngredient)
            .where(RecipeIngredient.recipe_id == recipe_id, RecipeIngredient.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )
        await _add_ingredients(
            session, household_id=household_id, recipe_id=recipe_id, lines=data.ingredients
        )
    await emit(
        session,
        type="recipe.updated",
        household_id=household_id,
        payload={"recipe_id": str(recipe_id)},
    )
    await session.flush()
    await session.refresh(recipe, attribute_names=["version", "updated_at"])
    return recipe


async def import_from_url(url: str) -> RecipeImportResponse:
    """Fetch *url* (SSRF-guarded) and extract a recipe draft from its JSON-LD, falling back to
    ``recipe-scrapers`` (microdata/site parsers) on the already-fetched HTML. The draft is NOT
    persisted — the caller reviews + saves it via ``create_recipe``. Raises 422 if no Recipe is
    found on the page."""
    final_url, html = await safe_fetch(url)
    draft = extract_jsonld_recipe(html, final_url) or extract_with_scrapers(html, final_url)
    if draft is None:
        raise ProblemException(
            slug="import_no_recipe", title="Kein Rezept auf der Seite gefunden", status=422
        )
    return draft


async def delete_recipe(
    session: AsyncSession, *, household_id: uuid.UUID, recipe_id: uuid.UUID
) -> None:
    """Soft-delete a recipe + its ingredient lines. Emits ``recipe.deleted``."""
    recipe = await get_recipe(session, recipe_id=recipe_id)
    now = datetime.now(UTC)
    recipe.deleted_at = now
    await session.execute(
        update(RecipeIngredient)
        .where(RecipeIngredient.recipe_id == recipe_id, RecipeIngredient.deleted_at.is_(None))
        .values(deleted_at=now)
    )
    await emit(
        session,
        type="recipe.deleted",
        household_id=household_id,
        payload={"recipe_id": str(recipe_id)},
    )


def _photo_key(recipe_id: uuid.UUID) -> str:
    return f"recipe-{recipe_id}.jpg"


async def set_recipe_photo(
    session: AsyncSession, *, household_id: uuid.UUID, recipe_id: uuid.UUID, image: bytes
) -> Recipe:
    """Store the (already normalized) JPEG and point the recipe at it. Emits ``recipe.updated``."""
    recipe = await get_recipe(session, recipe_id=recipe_id)  # RLS-scoped; 404 if not ours
    key = _photo_key(recipe_id)
    get_storage().put(key, image)
    recipe.photo_key = key
    await emit(
        session,
        type="recipe.updated",
        household_id=household_id,
        payload={"recipe_id": str(recipe_id)},
    )
    await session.flush()
    await session.refresh(recipe, attribute_names=["version", "updated_at"])
    return recipe


def read_recipe_photo(recipe: Recipe) -> bytes | None:
    """Read the stored photo bytes for an already-loaded (RLS-scoped) recipe."""
    return get_storage().get(recipe.photo_key) if recipe.photo_key else None


async def clear_recipe_photo(
    session: AsyncSession, *, household_id: uuid.UUID, recipe_id: uuid.UUID
) -> None:
    recipe = await get_recipe(session, recipe_id=recipe_id)
    if recipe.photo_key:
        get_storage().delete(recipe.photo_key)
        recipe.photo_key = None
        await emit(
            session,
            type="recipe.updated",
            household_id=household_id,
            payload={"recipe_id": str(recipe_id)},
        )
        await session.flush()
