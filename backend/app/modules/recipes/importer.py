"""Extract a recipe draft from a page's schema.org/Recipe JSON-LD (KONZEPT §5.2 import pipeline,
primary path). Pure stdlib — the page HTML is fetched separately by the SSRF guard (kernel/fetch.py)
and passed in; this never touches the network. ``recipe-scrapers`` is the fallback for pages without
usable JSON-LD (``extract_with_scrapers`` — likewise HTML-only, no network).

The output is a *draft* (never persisted directly): the user reviews + corrects it before saving
(esp. the ingredient mapping). Limits guard against hostile pages (line counts, field lengths)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from html.parser import HTMLParser
from typing import Any

from app.modules.recipes.schemas import IngredientLine, RecipeImportResponse

_MAX_INGREDIENTS = 100
_MAX_STEPS_LEN = 20000
_MAX_TAGS = 20


class _LdJsonCollector(HTMLParser):
    """Collect the text of every ``<script type="application/ld+json">`` block."""

    def __init__(self) -> None:
        super().__init__()
        self._capturing = False
        self._buffer: list[str] = []
        self.blocks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("type") == "application/ld+json":
            self._capturing = True
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._capturing:
            self._capturing = False
            self.blocks.append("".join(self._buffer))

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._buffer.append(data)


def _find_recipe(node: Any) -> dict[str, Any] | None:
    """Depth-first search for a node whose @type is (or includes) "Recipe"; follows @graph."""
    if isinstance(node, list):
        for item in node:
            found = _find_recipe(item)
            if found is not None:
                return found
        return None
    if isinstance(node, dict):
        if "@graph" in node:
            found = _find_recipe(node["@graph"])
            if found is not None:
                return found
        raw_type = node.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(isinstance(t, str) and t.lower() == "recipe" for t in types):
            return node
    return None


def _to_servings(value: Any) -> int:
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return min(max(value, 1), 100)
    text = value[0] if isinstance(value, list) and value else value
    match = re.search(r"\d+", str(text or ""))
    return min(max(int(match.group()), 1), 100) if match else 1


def _steps_to_md(instructions: Any) -> str:
    if isinstance(instructions, str):
        return instructions.strip()
    if isinstance(instructions, list):
        parts: list[str] = []
        for item in instructions:
            if isinstance(item, str):
                parts.append(item.strip())
            elif isinstance(item, dict):
                if item.get("@type") == "HowToSection":
                    parts.append(_steps_to_md(item.get("itemListElement", [])))
                else:
                    text = item.get("text") or item.get("name")
                    if text:
                        parts.append(str(text).strip())
        return "\n\n".join(part for part in parts if part)
    return ""


def _to_tags(value: Any) -> list[str]:
    raw = value.split(",") if isinstance(value, str) else value if isinstance(value, list) else []
    tags = [str(tag).strip() for tag in raw]
    return [tag for tag in tags if tag][:_MAX_TAGS]


def _to_ingredients(value: Any) -> list[IngredientLine]:
    raw = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    lines: list[IngredientLine] = []
    for item in raw[:_MAX_INGREDIENTS]:
        text = str(item).strip()[:500]
        if text:
            lines.append(IngredientLine(raw_text=text))
    return lines


def extract_jsonld_recipe(html: str, source_url: str) -> RecipeImportResponse | None:
    """Return a recipe draft from the page's JSON-LD, or ``None`` if no usable Recipe is present."""
    collector = _LdJsonCollector()
    collector.feed(html)
    for block in collector.blocks:
        try:
            parsed = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        recipe = _find_recipe(parsed)
        if recipe is None:
            continue
        title = str(recipe.get("name") or "").strip()[:200]
        if not title:
            continue
        return RecipeImportResponse(
            title=title,
            servings=_to_servings(recipe.get("recipeYield")),
            steps_md=_steps_to_md(recipe.get("recipeInstructions"))[:_MAX_STEPS_LEN],
            tags=_to_tags(recipe.get("keywords")),
            source_url=source_url[:2000],
            ingredients=_to_ingredients(
                recipe.get("recipeIngredient") or recipe.get("ingredients")
            ),
        )
    return None


def extract_with_scrapers(html: str, source_url: str) -> RecipeImportResponse | None:
    """Fallback for pages without usable JSON-LD (P2-S3b): hand the already-fetched HTML to
    ``recipe-scrapers`` (microdata/RDFa + site-specific parsers). HTML-only — it never fetches (the
    SSRF guard already ran). Returns a draft, or ``None`` if nothing usable is found (or the dep is
    missing). Every accessor is defensive — the lib raises on absent fields."""
    try:
        from recipe_scrapers import scrape_html
    except ImportError:
        return None

    def _try(fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception:
            return default

    scraper = _try(lambda: scrape_html(html, org_url=source_url, supported_only=False), None)
    if scraper is None:
        return None
    title = str(_try(scraper.title, "") or "").strip()[:200]
    if not title:
        return None
    return RecipeImportResponse(
        title=title,
        servings=_to_servings(_try(scraper.yields, "")),
        steps_md=str(_try(scraper.instructions, "") or "")[:_MAX_STEPS_LEN],
        tags=[],
        source_url=source_url[:2000],
        ingredients=_to_ingredients(_try(scraper.ingredients, [])),
    )
