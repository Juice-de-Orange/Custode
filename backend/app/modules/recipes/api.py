"""Exported service interface — the only allowed synchronous cross-module entry into ``recipes``
(other modules import THIS, never internals). Cross-module reaction is preferred via events."""

from app.modules.recipes.service import (
    RecipeMacros,
    create_recipe,
    delete_recipe,
    get_ingredients,
    get_recipe,
    list_recipes,
    mark_cooked,
    recipe_macros,
    update_recipe,
)

__all__ = [
    "RecipeMacros",
    "create_recipe",
    "delete_recipe",
    "get_ingredients",
    "get_recipe",
    "list_recipes",
    "mark_cooked",
    "recipe_macros",
    "update_recipe",
]
