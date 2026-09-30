"""Exported service interface — the only allowed cross-module entry into ``nutrition`` (others
import THIS, never internals). ``recipes`` uses ``match_ingredient`` + ``names_for``."""

from app.modules.nutrition.service import (
    Candidate,
    IngredientMatch,
    NutritionResult,
    best_match,
    calculate,
    load_candidates,
    match_ingredient,
    names_for,
    search_ingredients,
)

__all__ = [
    "Candidate",
    "IngredientMatch",
    "NutritionResult",
    "best_match",
    "calculate",
    "load_candidates",
    "match_ingredient",
    "names_for",
    "search_ingredients",
]
