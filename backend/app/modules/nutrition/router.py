"""HTTP layer for ``nutrition`` — canonical-ingredient search (for the future mapping/override UI).
Auth-only; ingredients are global reference data (ADR-0031), so no household scoping."""

from __future__ import annotations

from fastapi import APIRouter

from app.kernel.auth.dependencies import CurrentPrincipal, ScopedSession
from app.modules.nutrition import service
from app.modules.nutrition.schemas import IngredientOut

ingredients_router = APIRouter(prefix="/v1/ingredients", tags=["ingredients"])


@ingredients_router.get("")
async def list_ingredients(
    principal: CurrentPrincipal, session: ScopedSession, q: str = ""
) -> list[IngredientOut]:
    rows = await service.search_ingredients(session, q)
    return [
        IngredientOut(
            id=row.id,
            name_de=row.name_de,
            name_en=row.name_en,
            category=row.category,
            default_unit=row.default_unit,
        )
        for row in rows
    ]
