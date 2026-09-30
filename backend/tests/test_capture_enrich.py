"""Pure unit tests for the optional LLM enrichment merge (ADR-0068). No DB, no Ollama — only the
deterministic-floor invariants of ``merge_enrichment``: routing is never touched by the LLM, the LLM
only fills empty free-text slots, tags are unioned, and an absent/garbage result is a no-op."""

from __future__ import annotations

from app.kernel.ports.llm import UNAVAILABLE_LLM, LlmResult
from app.modules.capture.enrich import merge_enrichment
from app.modules.capture.schemas import FollowUp, ParsedProposal


def _base(**kw: object) -> ParsedProposal:
    data: dict[str, object] = {"target": "shopping", "label": "Deo"}
    data.update(kw)
    return ParsedProposal.model_validate(data)


def test_unavailable_llm_returns_base_unchanged() -> None:
    base = _base(qty="2", tags=["arbeit"])
    assert merge_enrichment(base, UNAVAILABLE_LLM) == base


def test_non_dict_payload_returns_base_unchanged() -> None:
    base = _base()
    assert merge_enrichment(base, LlmResult(available=True, data=None)) == base


def test_llm_fills_only_empty_freetext_slots() -> None:
    base = _base(label="Deo", qty=None, unit=None, when=None)
    llm = LlmResult(
        available=True,
        data={"label": "Rasierschaum", "qty": "1", "unit": "Stk", "when": "morgen"},
    )
    out = merge_enrichment(base, llm)
    # label was already set deterministically -> never overwritten.
    assert out.label == "Deo"
    # empty slots are filled from the LLM.
    assert out.qty == "1"
    assert out.unit == "Stk"
    assert out.when == "morgen"


def test_routing_fields_always_come_from_base() -> None:
    base = _base(target="task", follow_up=FollowUp(label="Müll rausbringen"))
    # An LLM cannot move the proposal to shopping or invent/clear a follow-up.
    llm = LlmResult(available=True, data={"target": "shopping", "follow_up": {"label": "x"}})
    out = merge_enrichment(base, llm)
    assert out.target == "task"
    assert out.follow_up == FollowUp(label="Müll rausbringen")


def test_tags_are_unioned_deterministic_first_deduped() -> None:
    base = _base(tags=["arbeit"])
    llm = LlmResult(available=True, data={"tags": ["arbeit", "drogerie", "  ", 42, "drogerie"]})
    out = merge_enrichment(base, llm)
    assert out.tags == ["arbeit", "drogerie"]


def test_blank_llm_strings_are_ignored() -> None:
    base = _base(qty=None, unit=None)
    llm = LlmResult(available=True, data={"qty": "   ", "unit": ""})
    out = merge_enrichment(base, llm)
    assert out.qty is None
    assert out.unit is None
