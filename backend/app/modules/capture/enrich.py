"""Optional LLM enrichment of the deterministic Zuruf parse (ADR-0068, KONZEPT §5.17). Graceful
enhancement: the deterministic ``ParsedProposal`` is the source of truth for **routing**
(``target`` + ``follow_up`` — action chains are never invented by an LLM). The LLM may only refine
free-text fields (``label``/``qty``/``unit``/``assignee_hint``/``when``) and **add** tags. All merge
logic here is pure + unit-tested; a malformed or absent LLM result leaves the parse untouched."""

from __future__ import annotations

from typing import Any

from app.kernel.ports.llm import LlmResult
from app.modules.capture.schemas import ParsedProposal

# The structured-output schema handed to the LLM (Ollama ``format``). Deliberately a subset of
# ``ParsedProposal``: the LLM never sets ``target`` or ``follow_up`` (kept deterministic).
ENRICH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {"type": "string"},
        "qty": {"type": "string"},
        "unit": {"type": "string"},
        "assignee_hint": {"type": "string"},
        "when": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}


def build_prompt(raw_text: str) -> str:
    """A compact German instruction to normalise a Zuruf into the enrichment schema."""
    return (
        "Du hilfst, einen kurzen deutschen Zuruf für eine Haushalts-App zu strukturieren. "
        "Extrahiere nur, was klar im Text steht; gib ausschließlich JSON nach dem Schema zurück. "
        "Erfinde nichts. Felder, die unklar sind, lässt du weg.\n\n"
        f"Zuruf: {raw_text}"
    )


def _clean_str(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def merge_enrichment(base: ParsedProposal, llm: LlmResult) -> ParsedProposal:
    """Fold an LLM result into the deterministic parse. Returns ``base`` unchanged when the LLM is
    unavailable or its payload is unusable. ``target``/``follow_up`` always come from ``base``."""
    if not llm.available or not isinstance(llm.data, dict):
        return base
    data = llm.data

    # Free-text fields: prefer the LLM value only when the deterministic parse left the slot empty,
    # so an LLM can fill gaps but never overwrite a confident deterministic extraction.
    label = base.label or (_clean_str(data.get("label")) or "")
    qty = base.qty or _clean_str(data.get("qty"))
    unit = base.unit or _clean_str(data.get("unit"))
    assignee = base.assignee_hint or _clean_str(data.get("assignee_hint"))
    when = base.when or _clean_str(data.get("when"))

    # Tags: union (deterministic first), de-duplicated, ignoring non-strings.
    tags = list(base.tags)
    raw_tags = data.get("tags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            cleaned = _clean_str(tag)
            if cleaned and cleaned not in tags:
                tags.append(cleaned)

    return ParsedProposal(
        target=base.target,
        label=label or base.label,
        qty=qty,
        unit=unit,
        assignee_hint=assignee,
        tags=tags,
        when=when,
        follow_up=base.follow_up,
    )
