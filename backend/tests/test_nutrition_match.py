"""Unit tests for the canonical-ingredient matcher (``best_match``). Pure — no DB, no Docker."""

from __future__ import annotations

import uuid

from app.modules.nutrition.service import Candidate, best_match


def _cand(name_de: str, *names: str) -> Candidate:
    return Candidate(
        id=uuid.uuid4(),
        name_de=name_de,
        match_names=tuple(n.lower() for n in (name_de, *names)),
    )


# Pre-sorted longest-name first, like service._load_candidates.
_CANDIDATES = sorted(
    [
        _cand("Zwiebel", "Onion"),
        _cand("Mehl", "Flour"),
        _cand("Ei", "Egg", "Eier"),
        _cand("Tomate", "Tomato"),
        _cand("Tomatenmark", "Tomato paste"),
        _cand("Knoblauchzehe", "Garlic clove", "Knoblauch"),
    ],
    key=lambda c: len(c.name_de),
    reverse=True,
)


def _match(text: str) -> str | None:
    result = best_match(_CANDIDATES, text)
    return result.name_de if result else None


def test_exact_word_match() -> None:
    assert _match("250 g Mehl") == "Mehl"


def test_english_name_match() -> None:
    assert _match("2 onions, diced") == "Zwiebel"


def test_german_plural_via_prefix() -> None:
    assert _match("2 Zwiebeln, gewürfelt") == "Zwiebel"
    assert _match("3 Tomaten") == "Tomate"


def test_alias_match() -> None:
    assert _match("2 Eier") == "Ei"
    assert _match("1 Zehe Knoblauch") == "Knoblauchzehe"


def test_longer_name_wins() -> None:
    # "Tomatenmark" must beat "Tomate" (both prefix-match the word) — most specific wins.
    assert _match("2 EL Tomatenmark") == "Tomatenmark"


def test_short_name_no_false_prefix() -> None:
    # "Ei" (2 chars) must not prefix-match "eingelegtes"; nothing else matches -> None.
    assert _match("eingelegtes Gemüse") is None


def test_no_match() -> None:
    assert _match("200 ml Kokosmilch") is None


def test_empty_text() -> None:
    assert _match("   ") is None
