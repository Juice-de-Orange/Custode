"""Property tests for the points-economy invariants (KONZEPT §5.9), pure logic, no DB.

These mirror the rules enforced by ``economy.service.transfer``: double-entry conservation (the sum
across all accounts is always zero), balance = sum(to) - sum(from), and — when coverage is enforced
the way the service does it — no member/escrow account ever goes negative."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

SYSTEM = "system"
_MEMBERS = ["member:a", "member:b", "member:c", "escrow:x"]
_ACCOUNTS = [SYSTEM, *_MEMBERS]

# A movement is (from_account, to_account, amount > 0).
_movements = st.lists(
    st.tuples(
        st.sampled_from(_ACCOUNTS),
        st.sampled_from(_ACCOUNTS),
        st.integers(min_value=1, max_value=1000),
    ).filter(lambda m: m[0] != m[1]),
    min_size=0,
    max_size=200,
)


def _balances(movements: list[tuple[str, str, int]]) -> dict[str, int]:
    bal: dict[str, int] = dict.fromkeys(_ACCOUNTS, 0)
    for frm, to, amount in movements:
        bal[frm] -= amount
        bal[to] += amount
    return bal


def _balance_of(movements: list[tuple[str, str, int]], account: str) -> int:
    return sum(a for f, t, a in movements if t == account) - sum(
        a for f, t, a in movements if f == account
    )


@given(movements=_movements)
def test_double_entry_conserved(movements: list[tuple[str, str, int]]) -> None:
    """Every movement is +amount to one account and -amount to another, so the sum across ALL
    accounts (incl. system and escrow) is always exactly zero — the double-entry invariant."""
    assert sum(_balances(movements).values()) == 0


@given(movements=_movements, account=st.sampled_from(_ACCOUNTS))
def test_balance_equals_sum_to_minus_sum_from(
    movements: list[tuple[str, str, int]], account: str
) -> None:
    """A balance is a SUM (sum(to) - sum(from)), never a stored field."""
    assert _balances(movements)[account] == _balance_of(movements, account)


@given(
    requests=st.lists(
        st.tuples(
            st.sampled_from(_ACCOUNTS),
            st.sampled_from(_ACCOUNTS),
            st.integers(min_value=1, max_value=1000),
        ).filter(lambda m: m[0] != m[1]),
        min_size=0,
        max_size=200,
    )
)
def test_coverage_keeps_non_system_non_negative(
    requests: list[tuple[str, str, int]],
) -> None:
    """Applying transfers with the service's coverage rule (system mints freely; any other source
    must already hold >= amount) keeps every member/escrow balance >= 0 at all times."""
    bal: dict[str, int] = dict.fromkeys(_ACCOUNTS, 0)
    for frm, to, amount in requests:
        if frm != SYSTEM and bal[frm] < amount:
            continue  # the service raises 422 here; the booking never happens
        bal[frm] -= amount
        bal[to] += amount
        for account, value in bal.items():
            if account != SYSTEM:
                assert value >= 0
