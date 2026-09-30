"""HTTP layer for ``marketplace`` (KONZEPT §5.10). Thin: validate -> service -> response. Listings
are household-scoped (RLS); the escrow lives in the economy ledger. Trading is for adults/members —
children are excluded (marketplace-for-children default off, CLAUDE.md)."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import ScopedSession, require_role
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.marketplace import service
from app.modules.marketplace.models import AutoAcceptRule, MarketListing
from app.modules.marketplace.schemas import (
    AutoAcceptRuleCreate,
    AutoAcceptRuleResponse,
    ListingCreate,
    ListingResponse,
)

marketplace_router = APIRouter(prefix="/v1/marketplace", tags=["marketplace"])

# Trading is admin/member only — children are excluded (marketplace_children default off).
TraderPrincipal = Annotated[Principal, Depends(require_role(Role.admin, Role.member))]


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _listing_response(listing: MarketListing) -> ListingResponse:
    return ListingResponse(
        id=listing.id,
        task_instance_id=listing.task_instance_id,
        title=listing.title,
        seller_id=listing.seller_id,
        price=listing.price,
        status=listing.status,
        buyer_id=listing.buyer_id,
        created_at=listing.created_at,
    )


@marketplace_router.get("/listings")
async def list_listings(
    principal: TraderPrincipal,
    session: ScopedSession,
    status_filter: Annotated[
        Literal["open", "accepted", "settled", "reverted", "withdrawn", "all"],
        Query(alias="status"),
    ] = "open",
) -> list[ListingResponse]:
    _require_household(principal)
    listings = await service.list_listings(
        session, status=None if status_filter == "all" else status_filter
    )
    return [_listing_response(listing) for listing in listings]


@marketplace_router.post(
    "/listings", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_listing(
    payload: ListingCreate, principal: TraderPrincipal, session: ScopedSession
) -> ListingResponse:
    """List one of your own open task instances for sale; the price is reserved into escrow."""
    household_id = _require_household(principal)
    listing = await service.create_listing(
        session,
        household_id=household_id,
        seller_id=principal.user_id,
        task_instance_id=payload.task_instance_id,
        price=payload.price,
    )
    return _listing_response(listing)


@marketplace_router.post("/listings/{listing_id}/accept", dependencies=[Depends(require_csrf)])
async def accept_listing(
    listing_id: uuid.UUID, principal: TraderPrincipal, session: ScopedSession
) -> ListingResponse:
    """Accept an open listing — the task is reassigned to you; the escrow pays out on settlement."""
    household_id = _require_household(principal)
    listing = await service.accept_listing(
        session, household_id=household_id, buyer_id=principal.user_id, listing_id=listing_id
    )
    return _listing_response(listing)


@marketplace_router.post("/listings/{listing_id}/withdraw", dependencies=[Depends(require_csrf)])
async def withdraw_listing(
    listing_id: uuid.UUID, principal: TraderPrincipal, session: ScopedSession
) -> ListingResponse:
    """Seller withdraws an unsold listing; the escrow is released back."""
    household_id = _require_household(principal)
    listing = await service.withdraw_listing(
        session, household_id=household_id, seller_id=principal.user_id, listing_id=listing_id
    )
    return _listing_response(listing)


@marketplace_router.post("/listings/{listing_id}/settle", dependencies=[Depends(require_csrf)])
async def settle_listing(
    listing_id: uuid.UUID, principal: TraderPrincipal, session: ScopedSession
) -> ListingResponse:
    """Settle an accepted listing once its task is done — the escrow is paid out to the buyer."""
    household_id = _require_household(principal)
    listing = await service.settle_listing(
        session, household_id=household_id, listing_id=listing_id
    )
    return _listing_response(listing)


# --- Auto-accept rules -------------------------------------------------------


def _rule_response(rule: AutoAcceptRule) -> AutoAcceptRuleResponse:
    return AutoAcceptRuleResponse(
        id=rule.id,
        member_id=rule.member_id,
        template_id=rule.template_id,
        max_price=rule.max_price,
        active=rule.active,
    )


@marketplace_router.get("/auto-accept")
async def list_rules(
    principal: TraderPrincipal, session: ScopedSession
) -> list[AutoAcceptRuleResponse]:
    """The caller's own auto-accept rules."""
    _require_household(principal)
    rules = await service.list_rules(session, member_id=principal.user_id)
    return [_rule_response(r) for r in rules]


@marketplace_router.post(
    "/auto-accept", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_rule(
    payload: AutoAcceptRuleCreate, principal: TraderPrincipal, session: ScopedSession
) -> AutoAcceptRuleResponse:
    """Add a standing rule: auto-accept matching listings up to ``max_price``."""
    household_id = _require_household(principal)
    rule = await service.create_rule(
        session,
        household_id=household_id,
        member_id=principal.user_id,
        template_id=payload.template_id,
        max_price=payload.max_price,
    )
    return _rule_response(rule)


@marketplace_router.delete(
    "/auto-accept/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_rule(
    rule_id: uuid.UUID, principal: TraderPrincipal, session: ScopedSession
) -> None:
    _require_household(principal)
    await service.delete_rule(session, member_id=principal.user_id, rule_id=rule_id)
