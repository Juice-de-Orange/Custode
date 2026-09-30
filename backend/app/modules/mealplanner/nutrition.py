"""Aggregate the week's planned recipes into a nutrition summary (P6-S10, ADR-0056). Pure, DB-free
and deterministic — sums per-portion macros across the meals that reference a recipe. A step toward
the Phase-6 goal („Auto-Wochenpläne erfüllen Nährwertziele")."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

# Default acceptance band around a kcal target (KONZEPT §5.4: „Nährwertziele ±10 %").
TARGET_TOLERANCE = 0.1

TargetVerdict = Literal["under", "on_target", "over"]


@dataclass(frozen=True)
class MacroSum:
    """Summed per-portion macros over the counted meals, plus how many meals were counted and
    whether every one had complete data (``complete``) or some were estimated."""

    kcal: float
    protein_g: float
    fat_g: float
    carbs_g: float
    meals_counted: int
    confidence: str  # "complete" if every counted meal was complete, else "estimated"


def sum_macros(macros: Iterable[tuple[float, float, float, float, str]]) -> MacroSum:
    """Sum ``(kcal, protein_g, fat_g, carbs_g, confidence)`` tuples (one per planned recipe-meal).
    ``meals_counted`` is the number of tuples; ``confidence`` is ``complete`` only if every counted
    meal was complete (else ``estimated``). Empty input -> all zeros, ``complete``."""
    kcal = protein = fat = carbs = 0.0
    counted = 0
    all_complete = True
    for k, p, f, c, conf in macros:
        kcal += k
        protein += p
        fat += f
        carbs += c
        counted += 1
        if conf != "complete":
            all_complete = False
    return MacroSum(
        kcal=round(kcal, 1),
        protein_g=round(protein, 1),
        fat_g=round(fat, 1),
        carbs_g=round(carbs, 1),
        meals_counted=counted,
        confidence="complete" if all_complete else "estimated",
    )


def evaluate_target(
    kcal: float, target_kcal: float, tolerance: float = TARGET_TOLERANCE
) -> TargetVerdict:
    """Classify ``kcal`` against a goal (KONZEPT §5.4 „±10 %"): ``on_target`` within
    ``target_kcal ± tolerance``, else ``under``/``over``. A non-positive target is treated as
    ``on_target`` (no goal to miss). The evaluation primitive the auto-planner will reuse."""
    if target_kcal <= 0:
        return "on_target"
    band = target_kcal * tolerance
    if kcal < target_kcal - band:
        return "under"
    if kcal > target_kcal + band:
        return "over"
    return "on_target"
