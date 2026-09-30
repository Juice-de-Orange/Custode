"""Unit tests for the recipe exclusion filter (P6-S13, ADR-0058) — pure, no DB."""

from __future__ import annotations

from app.modules.mealplanner.filters import has_excluded_tag, normalize_tags


def test_normalize_tags_lowercases_strips_and_drops_blanks() -> None:
    assert normalize_tags([" Nuss ", "LAKTOSE", "", "  "]) == frozenset({"nuss", "laktose"})


def test_empty_excluded_excludes_nothing() -> None:
    assert has_excluded_tag(["nuss"], frozenset()) is False


def test_matches_case_insensitively() -> None:
    assert has_excluded_tag(["Nuss", "vegetarisch"], frozenset({"nuss"})) is True


def test_no_match_passes() -> None:
    assert has_excluded_tag(["vegetarisch", "schnell"], frozenset({"nuss", "laktose"})) is False


def test_recipe_without_tags_passes() -> None:
    assert has_excluded_tag([], frozenset({"nuss"})) is False
