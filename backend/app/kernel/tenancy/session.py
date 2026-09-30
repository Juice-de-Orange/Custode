"""Household-scoped DB session (RLS, ARCHITECTURE §9). The transaction-local
settings ``app.household_id`` and ``app.user_id`` drive every RLS policy:
household-scoped tables filter on ``app.household_id``; the global ``users`` table
is visible to self (``app.user_id``) or co-members of the active household.

``get_session`` derives the scope from the request principal. ``scoped_session``
sets an explicit scope — used to **create** a household (scope to the freshly
generated id) and in tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.auth.context import current_principal
from app.kernel.db.engine import get_maint_sessionmaker, get_sessionmaker

# Sentinel for "authenticated, no active household": a valid uuid that matches no
# real household, so household-scoped policies return 0 rows while the users
# self-policy (keyed on app.user_id) still passes. Cleaner than leaving the GUC
# unset, which would make ``current_setting(...)::uuid`` casts choke on ''.
_NIL_UUID = "00000000-0000-0000-0000-000000000000"

_SET_SCOPE = text(
    "SELECT set_config('app.household_id', :household_id, true), "
    "set_config('app.user_id', :user_id, true)"
)


async def _apply_scope(session: AsyncSession, household_id: str, user_id: str) -> None:
    await session.execute(_SET_SCOPE.bindparams(household_id=household_id, user_id=user_id))


async def get_session() -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        principal = current_principal()
        if principal is not None:
            household = (
                str(principal.household_id) if principal.household_id is not None else _NIL_UUID
            )
            await _apply_scope(session, household, str(principal.user_id))
        yield session


@asynccontextmanager
async def scoped_session(*, household_id: object, user_id: object) -> AsyncIterator[AsyncSession]:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session, session.begin():
        await _apply_scope(session, str(household_id), str(user_id))
        yield session


@asynccontextmanager
async def maint_session() -> AsyncIterator[AsyncSession]:
    """Cross-user/cross-household session for the maintenance role (``custode_maint``):
    the auth bootstrap (login / refresh lookup before the user is known), the outbox
    dispatcher, and retention jobs. No RLS scope is set — the ``maint_all`` policies
    grant broad access. Never hand this to request-driven business logic."""
    sessionmaker = get_maint_sessionmaker()
    async with sessionmaker() as session, session.begin():
        yield session
