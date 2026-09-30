"""Property tests for the marketplace escrow invariants (KONZEPT §5.10/§5.9 done-criterion):
the sum of all balances INCL. escrow stays constant and no member/escrow balance ever goes negative,
for any sequence of fund/list/accept/settle/withdraw operations. Pure logic, no DB — it models the
same coverage rule the service enforces via ``economy.transfer``."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

SYSTEM = "system"
_MEMBERS = ["member:a", "member:b", "member:c"]


class _Ledger:
    """A tiny append-only ledger model with the service's coverage rule (system mints freely; any
    other source must already hold the amount)."""

    def __init__(self) -> None:
        self.bal: dict[str, int] = {SYSTEM: 0}
        for m in _MEMBERS:
            self.bal[m] = 0

    def transfer(self, frm: str, to: str, amount: int) -> bool:
        if amount <= 0 or frm == to:
            return False
        if frm != SYSTEM and self.bal.get(frm, 0) < amount:
            return False  # service raises 422; no booking
        self.bal[frm] = self.bal.get(frm, 0) - amount
        self.bal[to] = self.bal.get(to, 0) + amount
        return True

    def total(self) -> int:
        return sum(self.bal.values())

    def assert_invariants(self) -> None:
        assert self.total() == 0, "double-entry: sum across all accounts incl. escrow must be 0"
        for account, value in self.bal.items():
            if account != SYSTEM:
                assert value >= 0, f"{account} went negative ({value})"


# Op encoding: (kind, a, b, amount). kind 0=fund member, 1=list (escrow), 2=settle, 3=withdraw.
_ops = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=3),
        st.integers(min_value=0, max_value=2),
        st.integers(min_value=0, max_value=2),
        st.integers(min_value=1, max_value=500),
    ),
    min_size=0,
    max_size=200,
)


@given(ops=_ops)
def test_escrow_sum_constant_and_never_negative(ops: list[tuple[int, int, int, int]]) -> None:
    led = _Ledger()
    escrow_seq = 0  # each listing gets a unique escrow account
    open_escrows: list[tuple[str, str, str]] = []  # (escrow, seller, buyer-or-empty)
    for kind, a, b, amount in ops:
        seller = _MEMBERS[a]
        if kind == 0:  # fund a member from system (mint)
            led.transfer(SYSTEM, seller, amount)
        elif kind == 1:  # list: reserve price into a fresh escrow (coverage-checked)
            escrow = f"escrow:{escrow_seq}"
            escrow_seq += 1
            if led.transfer(seller, escrow, amount):
                buyer = _MEMBERS[b] if _MEMBERS[b] != seller else ""
                open_escrows.append((escrow, seller, buyer))
        elif kind == 2 and open_escrows:  # settle: escrow -> buyer (or seller if no buyer)
            escrow, s, buyer = open_escrows.pop()
            target = buyer or s
            led.transfer(escrow, target, led.bal[escrow])
        elif kind == 3 and open_escrows:  # withdraw: escrow -> seller
            escrow, s, _buyer = open_escrows.pop()
            led.transfer(escrow, s, led.bal[escrow])
        led.assert_invariants()

    led.assert_invariants()
