"""HTTP layer for ``wearables`` (P9-S5, KONZEPT §5.15, ADR-0081).

Health data is Art. 9 GDPR: member-private (not household-private), consented per data type,
and deletable for real. **Children and guests are excluded** (Root-CLAUDE.md, like vault and
marketplace).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import RedirectResponse

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import ScopedSession, peek_access_user_id, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.kernel.ports.wearable import WearableOAuthPort, get_wearable_oauth
from app.kernel.tenancy.session import scoped_session
from app.logging import get_logger
from app.modules.accounts import api as accounts_api
from app.modules.wearables import service
from app.modules.wearables.schemas import (
    AuthorizeRequest,
    AuthorizeResponse,
    ConnectionResponse,
    ConsentUpdate,
)
from app.settings import get_settings

_log = get_logger("wearables.router")

wearables_router = APIRouter(prefix="/v1/wearables", tags=["wearables"])

# Wearables are for adults: children + guests are excluded (Root-CLAUDE.md — "keine Wearables
# für Kinder-Accounts"), like vault/marketplace/capture.
WearablePrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]

OAuthPort = Annotated[WearableOAuthPort, Depends(get_wearable_oauth)]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _redirect_uri() -> str:
    """The callback URL, built in exactly ONE place.

    Authorize and exchange must send byte-identical values — providers compare them — and a
    second, slightly different construction site is the classic way to break this flow."""
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/v1/wearables/oura/callback"


@wearables_router.get("/connections")
async def list_connections(
    principal: WearablePrincipal, session: ScopedSession
) -> list[ConnectionResponse]:
    """The caller's own connections — never a co-member's, not even for an admin (N-2).

    No feature-flag check: switching the flag off must not lock a member out of seeing what is
    stored about them."""
    _require_household(principal)
    conns = await service.list_connections(session, member_id=principal.user_id)
    return [await service.to_response(session, conn) for conn in conns]


@wearables_router.post("/oura/authorize", dependencies=[Depends(require_csrf)])
async def authorize(
    payload: AuthorizeRequest,
    principal: WearablePrincipal,
    session: ScopedSession,
    oauth: OAuthPort,
) -> AuthorizeResponse:
    """Start the OAuth flow. Returns the provider URL for the browser to navigate to.

    403 when the household flag is off, 409 when a connection already exists, 503 without a
    server crypto key or with the provider switched off — all of them BEFORE the user is sent
    away, so they never grant access we then have to discard."""
    household_id = _require_household(principal)
    await service.require_enabled(session, household_id=household_id)
    url = await service.begin_connect(
        session,
        oauth=oauth,
        household_id=household_id,
        member_id=principal.user_id,
        consent_types=payload.consent_types,
        redirect_uri=_redirect_uri(),
    )
    return AuthorizeResponse(authorize_url=url)


@wearables_router.get("/oura/callback", include_in_schema=False)
async def oura_callback(
    request: Request,
    oauth: OAuthPort,
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> Response:
    """Provider callback — formally **unauthenticated** (no ``require_role``), because a visitor
    whose session expired on the consent screen must get a friendly redirect, not a 401.

    But formally-unauthenticated is not the same as blind. The single-use ``state`` authenticates
    the **flow**; it says nothing about the **browser** presenting it. Both checks are needed:

    * ``state`` → which member started this, and with which consent choices.
    * access cookie → who is actually driving this browser right now. It is ``SameSite=Lax`` with
      ``path="/"``, so a top-level GET navigation from the provider carries it.

    Without the second check an attacker could start their own flow, send the authorize URL to
    somebody else, and have that person's consent — and their tokens — land in the attacker's
    row (BUGLOG 2026-07-30). For Art.-9 health data that is a breach, not an inconvenience.

    Answers with a 302 into the web app, never problem+json — the caller is a browser following
    a redirect, not an API client. Neither the code, the state nor any token appears in the
    redirect target."""
    if error or not code or not state:
        return _back(error="denied" if error else "state_invalid")
    try:
        pending = await service.consume_state(state)
    except service.ConnectRejected as exc:
        return _back(error=exc.slug)

    # The browser must belong to the member who started the flow. A missing session counts as a
    # mismatch: we would otherwise accept a grant we cannot attribute. Same answer for both
    # cases, so the response never reveals whether a state existed.
    browser_user_id = await peek_access_user_id(request)
    if browser_user_id is None or browser_user_id != pending.user_id:
        _log.warning("wearable_callback_browser_mismatch", provider=pending.provider)
        return _back(error="state_invalid")

    # Re-check the role against the CURRENT membership: up to ten minutes passed on the
    # provider's consent screen, and the account could have been demoted to child (or removed)
    # in the meantime. The route-level require_role guard does not run on this route.
    role = await accounts_api.get_active_role(
        user_id=pending.user_id, household_id=pending.household_id
    )
    if role not in (Role.admin, Role.member):
        return _back(error="forbidden")

    async with scoped_session(
        household_id=pending.household_id, user_id=pending.user_id
    ) as session:
        try:
            await service.complete_connect(
                session,
                oauth=oauth,
                pending=pending,
                code=code,
                redirect_uri=_redirect_uri(),
            )
        except service.ConnectRejected as exc:
            return _back(error=exc.slug)
        except ProblemException as exc:
            return _back(error=exc.slug)
    return _back(connected=pending.provider)


def _back(*, connected: str | None = None, error: str | None = None) -> RedirectResponse:
    base = get_settings().public_base_url.rstrip("/")
    query = f"connected={connected}" if connected else f"error={error}"
    return RedirectResponse(url=f"{base}/profile?{query}", status_code=status.HTTP_302_FOUND)


@wearables_router.patch(
    "/connections/{connection_id}/consents", dependencies=[Depends(require_csrf)]
)
async def update_consents(
    connection_id: uuid.UUID,
    payload: ConsentUpdate,
    principal: WearablePrincipal,
    session: ScopedSession,
) -> ConnectionResponse | None:
    """Replace the consented data types.

    Withdrawing a type erases its stored values immediately. Withdrawing the LAST type
    disconnects entirely and answers ``null`` — a connection without consent must not survive."""
    household_id = _require_household(principal)
    conn = await service.update_consents(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        connection_id=connection_id,
        consent_types=payload.consent_types,
    )
    return None if conn is None else await service.to_response(session, conn)


@wearables_router.delete(
    "/connections/{connection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_connection(
    connection_id: uuid.UUID, principal: WearablePrincipal, session: ScopedSession
) -> None:
    """Disconnect and erase — a hard delete, no trash window (Art. 9).

    Neither the household flag nor the crypto key nor the provider being reachable is required:
    getting rid of your own health data must never depend on an integration working."""
    household_id = _require_household(principal)
    await service.delete_connection(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        connection_id=connection_id,
    )
