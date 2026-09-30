"""Detect whether a recipe needs advance preparation the day before (Synergie S-02, ADR-0055). Pure,
DB-free and deterministic — the testable core of the „Vorbereiten am Vortag"-Task (thawing,
marinating, soaking, a dough that rests overnight). It scans the recipe's steps and tags for
lead-time cues and returns a short hint, or ``None`` when nothing needs doing ahead of time."""

from __future__ import annotations

from collections.abc import Iterable

# Lead-time cues (DE + EN), lower-cased substrings. The matched cue is surfaced as the task hint so
# the user sees *why* a prep task was created („auftauen", „marinieren", …).
_CUES: tuple[str, ...] = (
    "auftauen",
    "marinieren",
    "marinade",
    "einweichen",
    "über nacht",
    "ueber nacht",
    "vortag",
    "am vorabend",
    "gehen lassen",
    "quellen",
    "thaw",
    "defrost",
    "marinate",
    "soak",
    "overnight",
    "the day before",
    "let rise",
    "proof the dough",
)


def needs_prep(steps_md: str, tags: Iterable[str]) -> str | None:
    """Return the first lead-time cue found in ``steps_md`` or ``tags`` (case-insensitive), else
    ``None``. The returned string is the matched cue (e.g. ``"marinieren"``) for use in the task
    title; order of ``_CUES`` is the deterministic priority."""
    haystack = steps_md.lower() + "\n" + "\n".join(t.lower() for t in tags)
    for cue in _CUES:
        if cue in haystack:
            return cue
    return None
