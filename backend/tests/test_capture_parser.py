"""Unit tests for the deterministic Zuruf rule-parser (KONZEPT §5.17) — pure, no DB, no LLM."""

from __future__ import annotations

from app.modules.capture.parser import parse_capture


def test_buy_verb_makes_shopping_with_clean_label() -> None:
    p = parse_capture("Milch kaufen")
    assert p.target == "shopping"
    assert p.label == "Milch"


def test_quantity_and_unit_are_split_off_the_label() -> None:
    p = parse_capture("2 Liter Milch kaufen")
    assert p.target == "shopping"
    assert p.label == "Milch"
    assert p.qty == "2"
    assert p.unit == "Liter"


def test_task_hint_forces_task_target() -> None:
    p = parse_capture("#task Müll rausbringen")
    assert p.target == "task"
    assert p.label == "Müll rausbringen"


def test_liste_hint_forces_shopping_without_buy_verb() -> None:
    p = parse_capture("#liste Zahnpasta")
    assert p.target == "shopping"
    assert p.label == "Zahnpasta"


def test_at_name_becomes_assignee_hint() -> None:
    p = parse_capture("#task Spülmaschine ausräumen @max")
    assert p.target == "task"
    assert p.assignee_hint == "max"
    assert "max" not in p.label


def test_free_tags_are_collected() -> None:
    p = parse_capture("Brot holen #dringend")
    assert p.target == "shopping"
    assert p.label == "Brot"
    assert "dringend" in p.tags


def test_time_tag_becomes_when() -> None:
    p = parse_capture("#task Blumen gießen #heute")
    assert p.when == "heute"
    assert "heute" not in p.tags


def test_fallback_without_verb_or_hint_is_unsortiert() -> None:
    p = parse_capture("Kevin anrufen")
    assert p.target == "none"
    assert p.label == "Kevin anrufen"


def test_deo_reference_case_parses_to_clean_item_and_context_tag() -> None:
    # KONZEPT §5.17 Deo-Referenzfall — Parser-Ebene: sauberer Posten + Kontext als Tag.
    p = parse_capture("muss mir ein Deo für die Arbeit besorgen")
    assert p.target == "shopping"
    assert p.label == "Deo"
    assert "arbeit" in p.tags


def test_english_buy_verb() -> None:
    p = parse_capture("buy toothpaste")
    assert p.target == "shopping"
    assert p.label == "toothpaste"


def test_follow_up_clause_builds_an_action_chain() -> None:
    # Deo-Fall (KONZEPT §5.17): "… dann <task>" -> shopping item + armed follow-up task.
    p = parse_capture("Deo kaufen, dann in den Rucksack")
    assert p.target == "shopping"
    assert p.label == "Deo"
    assert p.follow_up is not None
    assert p.follow_up.label == "in den Rucksack"


def test_follow_up_label_is_kept_verbatim() -> None:
    p = parse_capture("Brot holen dann einpacken")
    assert p.label == "Brot"
    assert p.follow_up is not None
    assert p.follow_up.label == "einpacken"


def test_no_follow_up_without_connector() -> None:
    p = parse_capture("Milch kaufen")
    assert p.follow_up is None
