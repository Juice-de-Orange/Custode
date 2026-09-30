"""Unit tests for the nutrition calc core (parse_quantity + compute_nutrition). Pure, no DB."""

from __future__ import annotations

import uuid

from app.modules.nutrition.service import IngredientFacts, compute_nutrition, parse_quantity


def test_parse_quantity_grams() -> None:
    assert parse_quantity("250 g Mehl") == (250.0, "g")


def test_parse_quantity_decimal_and_fraction() -> None:
    assert parse_quantity("1,5 kg Kartoffeln") == (1.5, "kg")
    assert parse_quantity("1/2 TL Salz") == (0.5, "TL")


def test_parse_quantity_no_space() -> None:
    assert parse_quantity("200ml Milch") == (200.0, "ml")


def test_parse_quantity_word_is_returned_verbatim() -> None:
    # The ingredient word is returned as the token; compute decides it is not a real unit.
    assert parse_quantity("2 Zwiebeln") == (2.0, "Zwiebeln")


def test_parse_quantity_none() -> None:
    assert parse_quantity("etwas Pfeffer") == (None, None)


_MEHL = uuid.uuid4()
_ZWIEBEL = uuid.uuid4()
_FACTS = {
    _MEHL: IngredientFacts(
        grams_per_unit={"g": 1.0, "EL": 10.0},
        default_unit="g",
        per_100g=(364, 10, 1, 76, 0.3, 2.7),
    ),
    _ZWIEBEL: IngredientFacts(
        grams_per_unit={"Stück": 110.0, "g": 1.0},
        default_unit="Stück",
        per_100g=(40, 1.1, 0.1, 9.3, 4.2, 1.7),
    ),
}


def test_compute_grams_unit() -> None:
    result = compute_nutrition(_FACTS, [("250 g Mehl", _MEHL)], servings=1)
    assert result.kcal == 910.0  # 364 * 2.5
    assert result.confidence == "complete"
    assert (result.covered, result.total) == (1, 1)


def test_compute_default_unit_for_pieces() -> None:
    # "2 Zwiebeln": no real unit token -> default Stück (110 g) -> 220 g -> 40 * 2.2.
    result = compute_nutrition(_FACTS, [("2 Zwiebeln", _ZWIEBEL)], servings=1)
    assert result.kcal == 88.0


def test_compute_per_portion() -> None:
    result = compute_nutrition(_FACTS, [("250 g Mehl", _MEHL)], servings=2)
    assert result.kcal == 455.0  # 910 / 2


def test_compute_estimated_when_a_line_is_unmatched() -> None:
    result = compute_nutrition(_FACTS, [("250 g Mehl", _MEHL), ("etwas Pfeffer", None)], servings=1)
    assert result.confidence == "estimated"
    assert (result.covered, result.total) == (1, 2)
    assert result.kcal == 910.0  # only the matched + parseable line contributes


def test_compute_empty() -> None:
    result = compute_nutrition(_FACTS, [], servings=1)
    assert result.kcal == 0.0
    assert result.confidence == "estimated"  # total = 0 -> not complete
