"""Deterministic offline rule-parser for the Zuruf (KONZEPT §5.17, pipeline stage 1). No DB, no LLM
— this is the full base path (Leitplanke 7): the common patterns are covered, the rest becomes an
„Unsortiert"-capture for manual triage. The LLM enrichment (stage 2) lands in Phase 7.

It recognises: buy verbs (DE/EN) -> shopping item; forcing hint tags
(``#liste``/``#task``/``#notiz``); a leading quantity + unit; ``@Name`` -> assignee hint; ``#tags``
(and a ``für …``/``for …`` context phrase) -> tags; time tags -> ``when``. Everything is a pure
string transform; resolving ``@Name`` to a real user, or ``für die Arbeit`` to a routine, is
deliberately out of scope here."""

from __future__ import annotations

import re

from app.modules.capture.schemas import FollowUp, ParsedProposal, ProposalTarget

# Buy verbs anchor a shopping item (KONZEPT §5.17). Kept lowercase for case-insensitive matching.
_BUY_VERBS = frozenset(
    {"besorgen", "kaufen", "holen", "brauchen", "mitbringen", "buy", "get", "grab", "need"}
)
# Forcing hint tags override the heuristic: #liste -> shopping, #task -> task, #notiz -> note.
_TARGET_HINTS: dict[str, ProposalTarget] = {
    "liste": "shopping",
    "list": "shopping",
    "einkauf": "shopping",
    "task": "task",
    "aufgabe": "task",
    "notiz": "note",
    "note": "note",
}
# Time hint tags -> ``when`` (kept as a raw token; real due_at math is S9b).
_TIME_TAGS = frozenset(
    {
        "heute",
        "morgen",
        "übermorgen",
        "today",
        "tomorrow",
        "mo",
        "di",
        "mi",
        "do",
        "fr",
        "sa",
        "so",
    }
)
# Units recognised right after a quantity.
_UNITS = frozenset(
    {
        "x",
        "stk",
        "stück",
        "g",
        "kg",
        "l",
        "ml",
        "liter",
        "packung",
        "pkg",
        "dose",
        "dosen",
        "flasche",
        "flaschen",
        "pack",
    }
)
# Words dropped from the label: buy verbs, articles, modal/filler words (DE + EN).
_STOPWORDS = _BUY_VERBS | frozenset(
    {
        "muss",
        "müssen",
        "ich",
        "mir",
        "mich",
        "will",
        "möchte",
        "soll",
        "noch",
        "mal",
        "bitte",
        "ein",
        "eine",
        "einen",
        "einem",
        "der",
        "die",
        "das",
        "den",
        "dem",
        "und",
        "i",
        "to",
        "a",
        "an",
        "the",
        "some",
        "need",
        "please",
        "gotta",
    }
)
_ARTICLES = frozenset({"der", "die", "das", "den", "dem", "the", "a", "an"})

_TOKEN = re.compile(r"[@#][\wÄÖÜäöüß]+")
_WORD = re.compile(r"[\wÄÖÜäöüß.,]+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_FOR_PHRASE = re.compile(r"\b(?:für|for)\b(.*)$", re.IGNORECASE)
# An action-chain connector splits a primary clause from a follow-up task (Deo-Fall, §5.17):
# "Deo kaufen, dann in den Rucksack" -> item "Deo" + follow-up task "in den Rucksack".
_FOLLOW_UP = re.compile(r"(?:,\s*)?\b(?:dann|danach|then)\b\s*(.+)$|;\s*(.+)$", re.IGNORECASE)


def _words(text: str) -> list[str]:
    return _WORD.findall(text)


def parse_capture(raw_text: str) -> ParsedProposal:
    """Turn a free-text Zuruf into a structured proposal (deterministic, offline)."""
    text = raw_text.strip()

    assignee: str | None = None
    at_match = re.search(r"@([\wÄÖÜäöüß]+)", text)
    if at_match is not None:
        assignee = at_match.group(1)

    forced: ProposalTarget | None = None
    tags: list[str] = []
    when: str | None = None
    for tag in re.findall(r"#([\wÄÖÜäöüß]+)", text):
        low = tag.lower()
        if low in _TARGET_HINTS:
            forced = _TARGET_HINTS[low]
        elif low in _TIME_TAGS:
            when = low
        elif low not in tags:
            tags.append(low)

    # Strip @.. / #.. tokens; what remains is the natural-language body.
    body = _TOKEN.sub(" ", text)

    # Split off an action-chain follow-up ("…, dann <task>") before anything else — the tail is a
    # task label kept verbatim (readable, e.g. "in den Rucksack"); the head stays the primary body.
    follow_up: FollowUp | None = None
    fu_match = _FOLLOW_UP.search(body)
    if fu_match is not None:
        tail = fu_match.group(1) or fu_match.group(2) or ""
        fu_label = tail.strip(" .,")
        if fu_label:
            follow_up = FollowUp(label=fu_label)
        body = body[: fu_match.start()]

    # A buy verb anywhere (incl. trailing, e.g. „… besorgen") marks a shopping intent.
    has_buy = any(w.lower() in _BUY_VERBS for w in _words(body))

    # A „für …"/„for …" phrase is context (routine/recipient), not part of the label.
    for_match = _FOR_PHRASE.search(body)
    if for_match is not None:
        for word in _words(for_match.group(1)):
            low = word.lower()
            if low in _STOPWORDS or low in _ARTICLES:
                continue
            if low in _TIME_TAGS:
                when = low
            elif low not in tags:
                tags.append(low)
        body = body[: for_match.start()]

    # Extract a leading quantity (+ optional unit) and build the label from the rest.
    qty: str | None = None
    unit: str | None = None
    label_words: list[str] = []
    cleaned = [w for w in _words(body) if w.lower() not in _STOPWORDS]
    for idx, word in enumerate(cleaned):
        if qty is None and _NUMBER.fullmatch(word):
            qty = word
            nxt = cleaned[idx + 1].lower() if idx + 1 < len(cleaned) else None
            if nxt in _UNITS:
                unit = cleaned[idx + 1]
            continue
        if unit is not None and word == unit:
            continue
        if qty is not None and unit is None and word.lower() in _UNITS:
            unit = word
            continue
        label_words.append(word)

    label = " ".join(label_words).strip(" .,") or body.strip(" .,") or text
    target: ProposalTarget = forced if forced is not None else ("shopping" if has_buy else "none")

    return ParsedProposal(
        target=target,
        label=label,
        qty=qty,
        unit=unit,
        assignee_hint=assignee,
        tags=tags,
        when=when,
        follow_up=follow_up,
    )
