"""Unit tests for the meal-slot suggester (KONZEPT §5.4, ADR-0052) — pure, no DB, no Docker."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from hypothesis import given
from hypothesis import strategies as st

from app.modules.mealplanner.suggest import (
    Candidate,
    pick_for_target,
    pick_least_recently_cooked,
    pick_quickest,
    suggest_many,
)

_NOW = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)


def _id(n: int) -> uuid.UUID:
    return uuid.UUID(int=n)


def _days_ago(d: float) -> datetime:
    return _NOW - timedelta(days=d)


def test_never_cooked_wins_over_cooked() -> None:
    never = Candidate(id=_id(1), last_cooked_at=None)
    long_ago = Candidate(id=_id(2), last_cooked_at=_days_ago(100))
    assert pick_least_recently_cooked([long_ago, never], now=_NOW, lockout_days=7) == _id(1)


def test_oldest_cooked_wins_among_cooked() -> None:
    recent = Candidate(id=_id(1), last_cooked_at=_days_ago(10))
    older = Candidate(id=_id(2), last_cooked_at=_days_ago(40))
    assert pick_least_recently_cooked([recent, older], now=_NOW, lockout_days=7) == _id(2)


def test_lockout_drops_recently_cooked() -> None:
    # Both cooked inside the 7-day lockout -> nothing eligible.
    a = Candidate(id=_id(1), last_cooked_at=_days_ago(2))
    b = Candidate(id=_id(2), last_cooked_at=_days_ago(6))
    assert pick_least_recently_cooked([a, b], now=_NOW, lockout_days=7) is None


def test_lockout_boundary_is_inclusive() -> None:
    # Cooked exactly lockout_days ago is eligible again (<= cutoff).
    edge = Candidate(id=_id(1), last_cooked_at=_days_ago(7))
    assert pick_least_recently_cooked([edge], now=_NOW, lockout_days=7) == _id(1)


def test_lockout_zero_admits_everything() -> None:
    just_now = Candidate(id=_id(1), last_cooked_at=_days_ago(0))
    assert pick_least_recently_cooked([just_now], now=_NOW, lockout_days=0) == _id(1)


def test_exclude_ids_skips_already_planned() -> None:
    planned = Candidate(id=_id(1), last_cooked_at=None)
    other = Candidate(id=_id(2), last_cooked_at=_days_ago(30))
    pick = pick_least_recently_cooked(
        [planned, other], now=_NOW, lockout_days=7, exclude_ids=frozenset({_id(1)})
    )
    assert pick == _id(2)


def test_empty_when_all_excluded_or_locked() -> None:
    a = Candidate(id=_id(1), last_cooked_at=_days_ago(1))  # locked out
    b = Candidate(id=_id(2), last_cooked_at=None)  # excluded
    pick = pick_least_recently_cooked(
        [a, b], now=_NOW, lockout_days=7, exclude_ids=frozenset({_id(2)})
    )
    assert pick is None


def test_no_candidates_returns_none() -> None:
    assert pick_least_recently_cooked([], now=_NOW, lockout_days=7) is None


def test_deterministic_tiebreak_by_id_for_never_cooked() -> None:
    a = Candidate(id=_id(5), last_cooked_at=None)
    b = Candidate(id=_id(3), last_cooked_at=None)
    # Smaller id wins on a tie; order of input must not matter.
    assert pick_least_recently_cooked([a, b], now=_NOW, lockout_days=7) == _id(3)
    assert pick_least_recently_cooked([b, a], now=_NOW, lockout_days=7) == _id(3)


def test_deterministic_tiebreak_by_id_for_equal_cooked_dates() -> None:
    when = _days_ago(30)
    a = Candidate(id=_id(9), last_cooked_at=when)
    b = Candidate(id=_id(4), last_cooked_at=when)
    assert pick_least_recently_cooked([a, b], now=_NOW, lockout_days=7) == _id(4)


def test_suggest_many_picks_distinct_in_due_order() -> None:
    never = Candidate(id=_id(1), last_cooked_at=None)
    old = Candidate(id=_id(2), last_cooked_at=_days_ago(40))
    newer = Candidate(id=_id(3), last_cooked_at=_days_ago(20))
    picks = suggest_many([newer, old, never], count=3, now=_NOW, lockout_days=7)
    assert picks == [_id(1), _id(2), _id(3)]  # never, then oldest, then newer — all distinct


def test_suggest_many_stops_when_pool_exhausted() -> None:
    a = Candidate(id=_id(1), last_cooked_at=None)
    b = Candidate(id=_id(2), last_cooked_at=_days_ago(30))
    # Asking for 5 but only 2 eligible -> best-effort returns 2 (no duplicates, no padding).
    picks = suggest_many([a, b], count=5, now=_NOW, lockout_days=7)
    assert picks == [_id(1), _id(2)]


def test_suggest_many_honours_lockout_and_excludes() -> None:
    locked = Candidate(id=_id(1), last_cooked_at=_days_ago(2))  # within lockout
    excluded = Candidate(id=_id(2), last_cooked_at=None)
    free = Candidate(id=_id(3), last_cooked_at=_days_ago(30))
    picks = suggest_many(
        [locked, excluded, free],
        count=3,
        now=_NOW,
        lockout_days=7,
        exclude_ids=frozenset({_id(2)}),
    )
    assert picks == [_id(3)]


def test_suggest_many_zero_count_is_empty() -> None:
    a = Candidate(id=_id(1), last_cooked_at=None)
    assert suggest_many([a], count=0, now=_NOW, lockout_days=7) == []


# --- pick_for_target (P6-S12) ---


def test_pick_for_target_chooses_closest_kcal() -> None:
    cands = [(_id(1), 300.0), (_id(2), 690.0), (_id(3), 1200.0)]
    assert pick_for_target(cands, target_kcal=700.0, count=1) == [_id(2)]


def test_pick_for_target_orders_by_distance() -> None:
    cands = [(_id(1), 500.0), (_id(2), 720.0), (_id(3), 900.0)]
    # Distances to 700: 200, 20, 200 -> closest first (2), then tie 1 vs 3 broken by id.
    assert pick_for_target(cands, target_kcal=700.0, count=3) == [_id(2), _id(1), _id(3)]


def test_pick_for_target_excludes_and_is_best_effort() -> None:
    cands = [(_id(1), 700.0), (_id(2), 710.0)]
    picks = pick_for_target(cands, target_kcal=700.0, count=5, exclude_ids=frozenset({_id(1)}))
    assert picks == [_id(2)]  # fewer than count, excluded one dropped


def test_pick_for_target_empty_and_zero_count() -> None:
    assert pick_for_target([], target_kcal=700.0, count=3) == []
    assert pick_for_target([(_id(1), 700.0)], target_kcal=700.0, count=0) == []


@given(
    cands=st.lists(
        st.tuples(st.integers(min_value=1, max_value=200), st.floats(0.0, 3000.0)),
        min_size=1,
        max_size=30,
        unique_by=lambda c: c[0],
    ),
    target=st.floats(0.0, 3000.0),
    count=st.integers(min_value=0, max_value=10),
)
def test_pick_for_target_invariant_no_closer_dropped(
    cands: list[tuple[int, float]], target: float, count: int
) -> None:
    """No dropped recipe is strictly closer to the target than any picked one (P6-S12 invariant)."""
    candidates = [(uuid.UUID(int=i), kcal) for i, kcal in cands]
    picks = pick_for_target(candidates, target_kcal=target, count=count)
    assert len(picks) == min(count, len(candidates))
    assert len(set(picks)) == len(picks)  # distinct
    picked = set(picks)
    kcal_by_id = dict(candidates)
    worst_picked = max((abs(kcal_by_id[p] - target) for p in picks), default=0.0)
    for rid, kcal in candidates:
        if rid not in picked:
            assert abs(kcal - target) >= worst_picked


# --- least-effort ordering for a tired cook (P9, Synergie S-14) ----------------


def test_quickest_prefers_the_shortest_recipe() -> None:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    pick = pick_quickest(
        [
            Candidate(id=_id(1), last_cooked_at=None, total_minutes=90),
            Candidate(id=_id(2), last_cooked_at=None, total_minutes=20),
            Candidate(id=_id(3), last_cooked_at=None, total_minutes=45),
        ],
        now=now,
        lockout_days=7,
    )
    assert pick == _id(2)


def test_quickest_still_honours_the_repeat_lockout() -> None:
    """ "You are tired" must not become "eat the same thing every day"."""
    now = datetime(2026, 7, 27, tzinfo=UTC)
    pick = pick_quickest(
        [
            Candidate(id=_id(1), last_cooked_at=now - timedelta(days=1), total_minutes=10),
            Candidate(id=_id(2), last_cooked_at=None, total_minutes=60),
        ],
        now=now,
        lockout_days=7,
    )
    assert pick == _id(2)  # the 10-minute one is locked out


def test_quickest_honours_exclusions() -> None:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    pick = pick_quickest(
        [
            Candidate(id=_id(1), last_cooked_at=None, total_minutes=10),
            Candidate(id=_id(2), last_cooked_at=None, total_minutes=60),
        ],
        now=now,
        lockout_days=7,
        exclude_ids=frozenset({_id(1)}),
    )
    assert pick == _id(2)


def test_recipes_without_a_stated_time_sort_last() -> None:
    """An unknown effort is not evidence of a small one — suggesting it to an exhausted cook
    would be a guess dressed as help."""
    now = datetime(2026, 7, 27, tzinfo=UTC)
    pick = pick_quickest(
        [
            Candidate(id=_id(1), last_cooked_at=None, total_minutes=None),
            Candidate(id=_id(2), last_cooked_at=None, total_minutes=120),
        ],
        now=now,
        lockout_days=7,
    )
    assert pick == _id(2)


def test_quickest_is_deterministic_on_ties() -> None:
    now = datetime(2026, 7, 27, tzinfo=UTC)
    pool = [
        Candidate(id=_id(2), last_cooked_at=None, total_minutes=30),
        Candidate(id=_id(1), last_cooked_at=None, total_minutes=30),
    ]
    assert pick_quickest(pool, now=now, lockout_days=7) == pick_quickest(
        list(reversed(pool)), now=now, lockout_days=7
    )


def test_quickest_returns_none_on_an_empty_pool() -> None:
    assert pick_quickest([], now=datetime(2026, 7, 27, tzinfo=UTC), lockout_days=7) is None
