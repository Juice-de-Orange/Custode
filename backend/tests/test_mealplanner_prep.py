"""Unit tests for the advance-prep detector (Synergie S-02, ADR-0055) — pure, no DB."""

from __future__ import annotations

from app.modules.mealplanner.prep import needs_prep


def test_no_cue_returns_none() -> None:
    assert needs_prep("Gemüse schneiden, anbraten, würzen.", []) is None


def test_detects_thawing_in_steps() -> None:
    assert needs_prep("Das Hähnchen rechtzeitig auftauen, dann braten.", []) == "auftauen"


def test_detects_marinating_case_insensitive() -> None:
    assert needs_prep("Fleisch über Nacht MARINIEREN.", []) == "marinieren"


def test_detects_cue_in_tags() -> None:
    # "einweichen" precedes "über nacht" in the cue priority order.
    assert needs_prep("Einfaches Rezept.", ["vegetarisch", "über Nacht einweichen"]) == "einweichen"


def test_english_cues() -> None:
    assert needs_prep("Soak the beans overnight before cooking.", []) == "soak"


def test_priority_is_deterministic() -> None:
    # Both "auftauen" and "marinieren" present -> the earlier cue in _CUES wins (auftauen).
    assert needs_prep("Erst auftauen, dann marinieren.", []) == "auftauen"


def test_empty_inputs_return_none() -> None:
    assert needs_prep("", []) is None
