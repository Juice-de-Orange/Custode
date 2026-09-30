"""nutrition use-cases (KONZEPT §5.3): canonical-ingredient lookup + best-effort matching. The core
``best_match`` is pure (no DB), unit-testable without containers. Nutrition values + ``calculate``
come in S5. ``ingredients`` is global reference data (ADR-0031), read on the caller's session."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.nutrition.models import Ingredient, IngredientNutrition

_NON_WORD = re.compile(r"[^a-zäöüß ]+")
_QTY_RE = re.compile(r"^\s*(\d+/\d+|\d+(?:[.,]\d+)?)\s*([^\d\s]+)?")
_GENERIC_GRAMS = {
    "g": 1.0,
    "kg": 1000.0,
    "mg": 0.001,
    "ml": 1.0,
    "l": 1000.0,
    "dl": 100.0,
    "cl": 10.0,
}


@dataclass(frozen=True)
class IngredientMatch:
    id: uuid.UUID
    name_de: str


@dataclass(frozen=True)
class Candidate:
    id: uuid.UUID
    name_de: str
    match_names: tuple[str, ...]  # lowercased name_de, name_en, *aliases


def _words(text: str) -> set[str]:
    return set(_NON_WORD.sub(" ", text.lower()).split())


def best_match(candidates: list[Candidate], raw_text: str) -> IngredientMatch | None:
    """Best-effort match of a free-text line to a canonical ingredient. A name matches a word
    exactly, or (names >= 4 chars) as its prefix — catching German plurals
    (``Zwiebeln`` → ``Zwiebel``). Candidates must be sorted longest-name first (most specific wins).
    ``None`` if nothing matches (the user maps manually)."""
    words = _words(raw_text)
    if not words:
        return None
    for cand in candidates:
        for name in cand.match_names:
            if name in words or (len(name) >= 4 and any(w.startswith(name) for w in words)):
                return IngredientMatch(id=cand.id, name_de=cand.name_de)
    return None


async def load_candidates(session: AsyncSession) -> list[Candidate]:
    rows = (await session.execute(select(Ingredient))).scalars().all()
    candidates = [
        Candidate(
            id=row.id,
            name_de=row.name_de,
            match_names=tuple(n.lower() for n in (row.name_de, row.name_en, *row.aliases)),
        )
        for row in rows
    ]
    candidates.sort(key=lambda c: len(c.name_de), reverse=True)
    return candidates


async def match_ingredient(session: AsyncSession, raw_text: str) -> IngredientMatch | None:
    """Match one free-text line to a canonical ingredient (or ``None``)."""
    return best_match(await load_candidates(session), raw_text)


async def search_ingredients(
    session: AsyncSession, query: str, *, limit: int = 20
) -> list[Ingredient]:
    """List canonical ingredients, optionally filtered by a name substring (DE or EN)."""
    stmt = select(Ingredient).order_by(Ingredient.name_de).limit(limit)
    cleaned = query.strip().lower()
    if cleaned:
        like = f"%{cleaned}%"
        stmt = (
            select(Ingredient)
            .where(
                func.lower(Ingredient.name_de).like(like)
                | func.lower(Ingredient.name_en).like(like)
            )
            .order_by(Ingredient.name_de)
            .limit(limit)
        )
    return list((await session.execute(stmt)).scalars().all())


async def names_for(session: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Resolve canonical ingredient ids to their German names (for cross-module display)."""
    if not ids:
        return {}
    rows = (
        await session.execute(
            select(Ingredient.id, Ingredient.name_de).where(Ingredient.id.in_(ids))
        )
    ).all()
    return {row[0]: row[1] for row in rows}


def parse_quantity(raw_text: str) -> tuple[float | None, str | None]:
    """Extract a leading quantity + unit token from a free-text line. ``"250 g Mehl"`` -> (250.0,
    "g"); ``"2 Zwiebeln"`` -> (2.0, "Zwiebeln") [the caller decides if the token is a real unit];
    ``"etwas Salz"`` -> (None, None). Handles decimals (``1,5``) and simple fractions (``1/2``)."""
    match = _QTY_RE.match(raw_text)
    if not match:
        return (None, None)
    num = match.group(1)
    if "/" in num:
        a, b = num.split("/")
        qty = float(a) / float(b) if float(b) else None
    else:
        qty = float(num.replace(",", "."))
    return (qty, match.group(2))


@dataclass(frozen=True)
class IngredientFacts:
    grams_per_unit: dict[str, float]
    default_unit: str
    per_100g: tuple[float, float, float, float, float, float]  # kcal,protein,fat,carbs,sugar,fiber


@dataclass(frozen=True)
class NutritionResult:
    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    sugar_g: float
    fiber_g: float
    confidence: str  # "complete" if every line counted, else "estimated"
    covered: int
    total: int


def _line_grams(facts: IngredientFacts, qty: float, token: str | None) -> float:
    units = facts.grams_per_unit
    if token and token in units:
        return qty * units[token]
    if token and token.lower() in _GENERIC_GRAMS:
        return qty * _GENERIC_GRAMS[token.lower()]
    # No recognized unit -> assume the ingredient's default unit (e.g. "2 Zwiebeln" -> 2 Stück).
    factor = units.get(facts.default_unit) or units.get("g") or 1.0
    return qty * factor


def compute_nutrition(
    facts_by_id: dict[uuid.UUID, IngredientFacts],
    lines: list[tuple[str, uuid.UUID | None]],
    servings: int,
) -> NutritionResult:
    """Pure per-portion nutrition. A line counts only with a matched ingredient that has nutrition
    data AND a parseable quantity; otherwise the result is flagged ``estimated``."""
    totals = [0.0] * 6
    covered = 0
    for raw_text, ingredient_id in lines:
        facts = facts_by_id.get(ingredient_id) if ingredient_id else None
        qty, token = parse_quantity(raw_text)
        if facts is None or qty is None:
            continue
        scale = _line_grams(facts, qty, token) / 100.0
        totals = [
            total + value * scale for total, value in zip(totals, facts.per_100g, strict=True)
        ]
        covered += 1
    per = [round(total / max(servings, 1), 1) for total in totals]
    total_lines = len(lines)
    confidence = "complete" if total_lines and covered == total_lines else "estimated"
    return NutritionResult(
        kcal=per[0],
        protein_g=per[1],
        fat_g=per[2],
        carbs_g=per[3],
        sugar_g=per[4],
        fiber_g=per[5],
        confidence=confidence,
        covered=covered,
        total=total_lines,
    )


async def calculate(
    session: AsyncSession, *, lines: list[tuple[str, uuid.UUID | None]], servings: int
) -> NutritionResult:
    """Per-portion nutrition for a recipe's ingredient lines (raw_text + matched ingredient_id)."""
    ids = [ingredient_id for (_, ingredient_id) in lines if ingredient_id is not None]
    facts_by_id: dict[uuid.UUID, IngredientFacts] = {}
    if ids:
        rows = (
            await session.execute(
                select(
                    Ingredient.id,
                    Ingredient.grams_per_unit,
                    Ingredient.default_unit,
                    IngredientNutrition.kcal,
                    IngredientNutrition.protein_g,
                    IngredientNutrition.fat_g,
                    IngredientNutrition.carbs_g,
                    IngredientNutrition.sugar_g,
                    IngredientNutrition.fiber_g,
                )
                .join(IngredientNutrition, IngredientNutrition.ingredient_id == Ingredient.id)
                .where(Ingredient.id.in_(ids))
            )
        ).all()
        for row in rows:
            facts_by_id[row[0]] = IngredientFacts(
                grams_per_unit=row[1],
                default_unit=row[2],
                per_100g=(row[3], row[4], row[5], row[6], row[7], row[8]),
            )
    return compute_nutrition(facts_by_id, lines, servings)
