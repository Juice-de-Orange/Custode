"""Unit tests for the week macro aggregation (P6-S10, ADR-0056) — pure, no DB."""

from __future__ import annotations

from app.modules.mealplanner.nutrition import evaluate_target, sum_macros


def test_empty_is_zero_and_complete() -> None:
    result = sum_macros([])
    assert result.kcal == 0.0
    assert result.meals_counted == 0
    assert result.confidence == "complete"


def test_sums_macros_and_counts_meals() -> None:
    result = sum_macros(
        [
            (500.0, 30.0, 20.0, 40.0, "complete"),
            (700.0, 25.0, 30.0, 80.0, "complete"),
        ]
    )
    assert result.kcal == 1200.0
    assert result.protein_g == 55.0
    assert result.fat_g == 50.0
    assert result.carbs_g == 120.0
    assert result.meals_counted == 2
    assert result.confidence == "complete"


def test_any_estimated_makes_the_sum_estimated() -> None:
    result = sum_macros(
        [
            (500.0, 30.0, 20.0, 40.0, "complete"),
            (300.0, 10.0, 5.0, 50.0, "estimated"),
        ]
    )
    assert result.meals_counted == 2
    assert result.confidence == "estimated"


def test_rounds_to_one_decimal() -> None:
    result = sum_macros([(100.16, 1.94, 2.31, 3.0, "complete")])
    assert result.kcal == 100.2
    assert result.protein_g == 1.9
    assert result.fat_g == 2.3


def test_evaluate_target_within_band_is_on_target() -> None:
    # 700 kcal vs 700 target (±10% = 630..770).
    assert evaluate_target(700.0, 700.0) == "on_target"
    assert evaluate_target(640.0, 700.0) == "on_target"
    assert evaluate_target(760.0, 700.0) == "on_target"


def test_evaluate_target_under_and_over() -> None:
    assert evaluate_target(600.0, 700.0) == "under"  # below 630
    assert evaluate_target(800.0, 700.0) == "over"  # above 770


def test_evaluate_target_band_edges_inclusive() -> None:
    assert evaluate_target(630.0, 700.0) == "on_target"  # exactly -10%
    assert evaluate_target(770.0, 700.0) == "on_target"  # exactly +10%


def test_evaluate_target_non_positive_target_is_on_target() -> None:
    assert evaluate_target(1234.0, 0.0) == "on_target"


def test_evaluate_target_custom_tolerance() -> None:
    # ±5% band: 700 -> 665..735.
    assert evaluate_target(660.0, 700.0, tolerance=0.05) == "under"
    assert evaluate_target(700.0, 700.0, tolerance=0.05) == "on_target"
