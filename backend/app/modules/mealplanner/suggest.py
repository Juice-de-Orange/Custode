"""Auto-suggest a recipe for a meal slot (KONZEPT §5.4, ADR-0052). Pure, DB-free, LLM-free and
deterministic — the testable core of „neu würfeln". It implements the repeat-lockout (never propose
a recipe cooked within ``lockout_days``) and a least-recently-cooked ordering on top of the
``last_cooked_at`` history that P6-S3 records."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# Aware sentinel that sorts before any real ``last_cooked_at`` (used only for never-cooked rows,
# which are pinned ahead by the leading group flag — the value is just an internal tiebreak filler).
_NEVER = datetime(1, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class Candidate:
    """A recipe the suggester may pick: its id and when it was last cooked (None = never).

    ``total_minutes`` (prep + cook, ``None`` when the recipe does not say) is additive and only
    read by ``pick_quickest`` — existing callers keep the least-recently-cooked behaviour."""

    id: uuid.UUID
    last_cooked_at: datetime | None
    total_minutes: int | None = None


def pick_least_recently_cooked(
    candidates: Iterable[Candidate],
    *,
    now: datetime,
    lockout_days: int,
    exclude_ids: frozenset[uuid.UUID] = frozenset(),
) -> uuid.UUID | None:
    """Pick the recipe that is most „due" to be cooked again, or ``None`` if none qualifies.

    Rules (deterministic):
    - drop anything in ``exclude_ids`` (already planned this week / the current cell);
    - drop anything cooked within ``lockout_days`` of ``now`` (repeat-lockout);
    - order the rest: never-cooked first, then the oldest ``last_cooked_at``; ties broken by ``id``.

    ``now`` and every ``last_cooked_at`` must share aware-ness (both timezone-aware in practice).
    """
    cutoff = now - timedelta(days=lockout_days)
    eligible = [
        c
        for c in candidates
        if c.id not in exclude_ids and (c.last_cooked_at is None or c.last_cooked_at <= cutoff)
    ]
    if not eligible:
        return None

    # Uniform key: group 0 = never-cooked (pinned first), group 1 = cooked-by-date; ties by id.
    def _key(c: Candidate) -> tuple[int, datetime, uuid.UUID]:
        return (0, _NEVER, c.id) if c.last_cooked_at is None else (1, c.last_cooked_at, c.id)

    eligible.sort(key=_key)
    return eligible[0].id


def suggest_many(
    candidates: Iterable[Candidate],
    *,
    count: int,
    now: datetime,
    lockout_days: int,
    exclude_ids: frozenset[uuid.UUID] = frozenset(),
) -> list[uuid.UUID]:
    """Pick up to ``count`` **distinct** recipes to fill several slots at once („Woche würfeln").

    Greedy least-recently-cooked: each pick is added to the running exclude set so the batch never
    repeats a recipe (variety across the week). Returns fewer than ``count`` — possibly empty — when
    the eligible pool runs out (best-effort; the caller fills what it can). Deterministic."""
    pool = list(candidates)
    chosen: list[uuid.UUID] = []
    used = set(exclude_ids)
    for _ in range(max(count, 0)):
        pick = pick_least_recently_cooked(
            pool, now=now, lockout_days=lockout_days, exclude_ids=frozenset(used)
        )
        if pick is None:
            break
        chosen.append(pick)
        used.add(pick)
    return chosen


def pick_for_target(
    candidates: Iterable[tuple[uuid.UUID, float]],
    *,
    target_kcal: float,
    count: int,
    exclude_ids: frozenset[uuid.UUID] = frozenset(),
) -> list[uuid.UUID]:
    """Pick up to ``count`` **distinct** recipes whose per-portion kcal is closest to the target
    (P6-S12). Each candidate is ``(id, kcal)``. Deterministic: sorted by absolute distance to the
    target, ties broken by ``id``; ``exclude_ids`` are dropped. Best-effort — returns fewer than
    ``count`` if the eligible pool is smaller. Invariant: no dropped eligible recipe is strictly
    closer to the target than any picked one."""
    eligible = [(rid, kcal) for rid, kcal in candidates if rid not in exclude_ids]
    eligible.sort(key=lambda c: (abs(c[1] - target_kcal), c[0]))
    return [rid for rid, _ in eligible[: max(count, 0)]]


def pick_quickest(
    candidates: Iterable[Candidate],
    *,
    now: datetime,
    lockout_days: int,
    exclude_ids: frozenset[uuid.UUID] = frozenset(),
) -> uuid.UUID | None:
    """The **least effortful** eligible recipe (P9, Synergie S-14 applied to cooking).

    Same eligibility rules as ``pick_least_recently_cooked`` — the repeat-lockout and the
    exclusions still hold, because "you are tired" must not become "eat the same thing daily".
    Only the ordering changes: shortest total time first, ties broken by least-recently-cooked,
    then by id (deterministic).

    Recipes without a stated time sort **last**: an unknown effort is not evidence of a small
    one, and suggesting it to someone who is exhausted would be a guess dressed as help."""
    cutoff = now - timedelta(days=lockout_days)
    eligible = [
        c
        for c in candidates
        if c.id not in exclude_ids and (c.last_cooked_at is None or c.last_cooked_at <= cutoff)
    ]
    if not eligible:
        return None

    def _key(c: Candidate) -> tuple[int, int, datetime, uuid.UUID]:
        known = 0 if c.total_minutes is not None else 1
        return (known, c.total_minutes or 0, c.last_cooked_at or _NEVER, c.id)

    eligible.sort(key=_key)
    return eligible[0].id
