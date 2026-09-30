"""Recipe exclusion filter for auto-fill (P6-S13, ADR-0058). Pure, DB-free and deterministic — keeps
recipes carrying an excluded tag (allergens, diet exclusions) out of the auto-planner. Matching is
case-insensitive on the recipe's tags; ingredient ``raw_text`` is **not** parsed here (the tag is
the curated signal — a later slice may map canonical allergens from ingredients)."""

from __future__ import annotations

from collections.abc import Iterable


def normalize_tags(tags: Iterable[str]) -> frozenset[str]:
    """Lower-case + strip a tag list into a comparable set (drops blanks)."""
    return frozenset(t.strip().lower() for t in tags if t.strip())


def has_excluded_tag(recipe_tags: Iterable[str], excluded: frozenset[str]) -> bool:
    """True if any of the recipe's tags is in ``excluded`` (both compared case-insensitively).
    ``excluded`` is expected already normalized (see ``normalize_tags``); an empty set excludes
    nothing."""
    if not excluded:
        return False
    return bool(normalize_tags(recipe_tags) & excluded)
