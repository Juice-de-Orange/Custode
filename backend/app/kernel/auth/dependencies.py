"""FastAPI auth dependencies. ``get_current_principal`` resolves the access cookie to
a :class:`Principal` and binds it to the request context, so a sibling scoped session
applies the right RLS scope. ``get_scoped_session`` depends on the principal, which
guarantees it runs *after* the binding (FastAPI resolves the dependency it needs
first) — the contextvar would otherwise be unset when the session opens.

Use the ``Annotated`` aliases in routes (modern FastAPI style; also keeps the
``Depends(...)`` calls out of parameter defaults, which ruff B008 forbids)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.auth.access import load_access
from app.kernel.auth.context import Principal, Role, set_principal
from app.kernel.http.cookies import access_cookie_name
from app.kernel.http.problem import ProblemException
from app.kernel.tenancy.session import get_session
from app.settings import get_settings


async def get_current_principal(request: Request) -> Principal:
    """Resolve the access cookie to the acting principal and bind it to the request
    context. 401 if the cookie is absent, unknown, expired, or Redis is down."""
    token = request.cookies.get(access_cookie_name(get_settings()))
    claims = await load_access(token) if token else None
    if claims is None:
        raise ProblemException(slug="unauthorized", title="Nicht angemeldet", status=401)
    principal = Principal(
        user_id=claims.user_id,
        family_id=claims.family_id,
        household_id=claims.household_id,
        role=claims.role,
    )
    set_principal(principal)
    return principal


async def peek_access_user_id(request: Request) -> uuid.UUID | None:
    """Who is driving this browser, or ``None`` — **without** binding a principal or raising.

    For the one route family that is formally unauthenticated but still arrives in a real
    browser: an OAuth provider callback. It cannot use ``get_current_principal`` (that would
    make the route 401 for a legitimately session-less visitor and bind an RLS scope the
    callback must take from its own state instead), yet it must not be blind to the session
    either.

    Why it works: the access cookie is ``SameSite=Lax`` with ``path="/"``
    (``kernel/http/cookies.py``), so a **top-level GET navigation** from the provider carries
    it. Anything cross-site and non-top-level does not — which is exactly the distinction we
    want.

    See BUGLOG 2026-07-30: binding a callback only to a server-side ``state`` authenticates the
    *flow*, never the *browser*. An attacker could start their own flow and hand the authorize
    URL to somebody else, whose consent then lands in the attacker's row."""
    token = request.cookies.get(access_cookie_name(get_settings()))
    claims = await load_access(token) if token else None
    return claims.user_id if claims is not None else None


CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]


async def get_scoped_session(principal: CurrentPrincipal) -> AsyncIterator[AsyncSession]:
    """RLS-scoped DB session, guaranteed to open *after* the principal is bound."""
    async for session in get_session():
        yield session


ScopedSession = Annotated[AsyncSession, Depends(get_scoped_session)]


def require_role(*roles: Role) -> Callable[[Principal], Awaitable[Principal]]:
    """Dependency factory: require the active-household role to be one of ``roles``
    (403 otherwise). A ``None`` role — authenticated but no active household — never
    matches, so it is rejected too."""

    async def _dep(principal: CurrentPrincipal) -> Principal:
        if principal.role not in roles:
            raise ProblemException(slug="forbidden", title="Keine Berechtigung", status=403)
        return principal

    return _dep


AdminPrincipal = Annotated[Principal, Depends(require_role(Role.admin))]
