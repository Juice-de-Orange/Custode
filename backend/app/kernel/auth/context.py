"""Request-scoped principal (who is acting, in which household, with which role).
Phase 0 provides the carrier; real authentication lands in Phase 1."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    admin = "admin"
    member = "member"
    child = "child"
    guest = "guest"


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is acting. ``family_id`` is the login-session (rotation) family the access
    token belongs to — household switches re-mint the access token within it.
    ``household_id``/``role`` are ``None`` when no household is active yet (just-
    registered user, or before a household switch)."""

    user_id: uuid.UUID
    family_id: uuid.UUID
    household_id: uuid.UUID | None = None
    role: Role | None = None


_current: ContextVar[Principal | None] = ContextVar("current_principal", default=None)


def set_principal(principal: Principal | None) -> None:
    _current.set(principal)


def current_principal() -> Principal | None:
    return _current.get()
