"""HTTP layer for ``recipes`` (KONZEPT §5.2). Thin: validate -> service -> response. Recipes are
household-scoped (RLS) with PATCH + If-Match (ADR-0029); GET/PATCH carry an ETag (= version)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.auth.context import Principal
from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.images import normalize_image
from app.kernel.storage import get_storage
from app.modules.nutrition import api as nutrition_api
from app.modules.recipes import service
from app.modules.recipes.models import Recipe, RecipeIngredient
from app.modules.recipes.schemas import (
    IngredientResponse,
    NutritionOut,
    RecipeCreate,
    RecipeImportRequest,
    RecipeImportResponse,
    RecipeResponse,
    RecipeSummary,
    RecipeUpdate,
)

recipes_router = APIRouter(prefix="/v1/recipes", tags=["recipes"])


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _recipe_response(
    recipe: Recipe, ingredients: list[RecipeIngredient], names: dict[uuid.UUID, str]
) -> RecipeResponse:
    return RecipeResponse(
        id=recipe.id,
        title=recipe.title,
        servings=recipe.servings,
        steps_md=recipe.steps_md,
        prep_minutes=recipe.prep_minutes,
        cook_minutes=recipe.cook_minutes,
        tags=list(recipe.tags),
        source_url=recipe.source_url,
        ingredients=[
            IngredientResponse(
                raw_text=i.raw_text,
                qty=i.qty,
                unit=i.unit,
                ingredient_id=i.ingredient_id,
                ingredient_name=names.get(i.ingredient_id) if i.ingredient_id else None,
            )
            for i in ingredients
        ],
        version=recipe.version,
        has_photo=recipe.photo_key is not None,
        last_cooked_at=recipe.last_cooked_at,
    )


async def _build_response(session: AsyncSession, recipe: Recipe) -> RecipeResponse:
    """Full recipe response: lines + their canonical names (resolved via nutrition.api)."""
    ingredients = await service.get_ingredients(session, recipe_id=recipe.id)
    ids = [i.ingredient_id for i in ingredients if i.ingredient_id is not None]
    names = await nutrition_api.names_for(session, ids)
    return _recipe_response(recipe, ingredients, names)


@recipes_router.get("")
async def list_recipes(principal: CurrentPrincipal, session: ScopedSession) -> list[RecipeSummary]:
    recipes = await service.list_recipes(session)
    return [
        RecipeSummary(
            id=r.id,
            title=r.title,
            servings=r.servings,
            tags=list(r.tags),
            has_photo=r.photo_key is not None,
            last_cooked_at=r.last_cooked_at,
        )
        for r in recipes
    ]


@recipes_router.post("", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)])
async def create_recipe(
    payload: RecipeCreate,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> RecipeResponse:
    household_id = _require_household(principal)
    recipe = await service.create_recipe(session, household_id=household_id, data=payload)
    response.headers["ETag"] = f'"{recipe.version}"'
    return await _build_response(session, recipe)


@recipes_router.post("/import", dependencies=[Depends(require_csrf)])
async def import_recipe(
    payload: RecipeImportRequest, principal: CurrentPrincipal
) -> RecipeImportResponse:
    """Fetch + extract a recipe draft from a URL (SSRF-guarded). Returns the draft for review;
    nothing is saved until the user POSTs it to /v1/recipes."""
    _require_household(principal)
    return await service.import_from_url(payload.url)


@recipes_router.get("/{recipe_id}")
async def get_recipe(
    recipe_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> RecipeResponse:
    recipe = await service.get_recipe(session, recipe_id=recipe_id)
    response.headers["ETag"] = f'"{recipe.version}"'
    return await _build_response(session, recipe)


@recipes_router.get("/{recipe_id}/nutrition")
async def recipe_nutrition(
    recipe_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> NutritionOut:
    """Per-portion nutrition for a recipe (computed on demand via nutrition.api)."""
    recipe = await service.get_recipe(session, recipe_id=recipe_id)
    ingredients = await service.get_ingredients(session, recipe_id=recipe_id)
    result = await nutrition_api.calculate(
        session,
        lines=[(i.raw_text, i.ingredient_id) for i in ingredients],
        servings=recipe.servings,
    )
    return NutritionOut(
        kcal=result.kcal,
        protein_g=result.protein_g,
        fat_g=result.fat_g,
        carbs_g=result.carbs_g,
        sugar_g=result.sugar_g,
        fiber_g=result.fiber_g,
        confidence=result.confidence,
        covered=result.covered,
        total=result.total,
    )


@recipes_router.patch("/{recipe_id}", dependencies=[Depends(require_csrf)])
async def update_recipe(
    recipe_id: uuid.UUID,
    payload: RecipeUpdate,
    request: Request,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> RecipeResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    recipe = await service.update_recipe(
        session,
        household_id=household_id,
        recipe_id=recipe_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{recipe.version}"'
    return await _build_response(session, recipe)


@recipes_router.delete(
    "/{recipe_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_csrf)]
)
async def delete_recipe(
    recipe_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_recipe(session, household_id=household_id, recipe_id=recipe_id)


_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MiB raw cap (before normalization)


@recipes_router.put("/{recipe_id}/photo", dependencies=[Depends(require_csrf)])
async def set_recipe_photo(
    recipe_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    file: UploadFile,
) -> RecipeResponse:
    """Upload/replace the recipe photo — re-encoded to JPEG (EXIF stripped) before storage.
    503 if no storage backend is configured (Graceful Enhancement)."""
    household_id = _require_household(principal)
    if not get_storage().enabled:
        raise ProblemException(
            slug="storage_unavailable", title="Foto-Upload nicht verfügbar", status=503
        )
    raw = await file.read(_MAX_UPLOAD_BYTES + 1)
    if len(raw) > _MAX_UPLOAD_BYTES:
        raise ProblemException(slug="file_too_large", title="Bild zu groß", status=413)
    recipe = await service.set_recipe_photo(
        session, household_id=household_id, recipe_id=recipe_id, image=normalize_image(raw)
    )
    return await _build_response(session, recipe)


@recipes_router.get("/{recipe_id}/photo")
async def get_recipe_photo(
    recipe_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> Response:
    """Stream the recipe photo (JPEG) to a household member; 404 if there is none."""
    recipe = await service.get_recipe(session, recipe_id=recipe_id)
    data = service.read_recipe_photo(recipe)
    if data is None:
        raise ProblemException(slug="not_found", title="Kein Foto", status=404)
    return Response(
        content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"}
    )


@recipes_router.delete(
    "/{recipe_id}/photo",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_recipe_photo(
    recipe_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.clear_recipe_photo(session, household_id=household_id, recipe_id=recipe_id)
