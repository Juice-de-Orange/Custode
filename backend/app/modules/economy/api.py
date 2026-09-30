"""Exported service interface — the only allowed synchronous cross-module entry into ``economy``
(other modules import THIS, never internals; ADR-0035). E.g. ``tasks`` credits a completion, a later
``marketplace`` moves points to/from escrow. ``economy`` itself imports no other module."""

from app.modules.economy.service import (
    balance,
    credit_task_completion,
    escrow_account,
    expire_member_balance,
    fairness_load,
    member_account,
    transfer,
)

__all__ = [
    "balance",
    "credit_task_completion",
    "escrow_account",
    "expire_member_balance",
    "fairness_load",
    "member_account",
    "transfer",
]
