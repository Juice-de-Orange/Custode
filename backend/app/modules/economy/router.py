"""HTTP layer for ``economy`` (KONZEPT §5.9). Thin: validate -> service -> response. The ledger is
household-scoped (RLS) and append-only; balances are computed sums (ADR-0035). Members read their
own balance + movements; admins can post a visible correction."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.kernel.auth.context import Principal, Role
from app.kernel.auth.dependencies import AdminPrincipal, CurrentPrincipal, ScopedSession
from app.kernel.http.conditional import parse_if_match
from app.kernel.http.csrf import require_csrf
from app.kernel.http.problem import ProblemException
from app.modules.economy import service
from app.modules.economy.models import LedgerEntry, Redemption, Reward
from app.modules.economy.schemas import (
    BalanceResponse,
    ChallengeResponse,
    ChallengeStanding,
    CorrectionRequest,
    FairnessEntry,
    FairnessResponse,
    LedgerEntryResponse,
    RedemptionResponse,
    RewardCreate,
    RewardResponse,
    RewardUpdate,
    ThanksRequest,
    ThanksResponse,
)

economy_router = APIRouter(prefix="/v1/economy", tags=["economy"])


def _require_household(principal: Principal) -> uuid.UUID:
    if principal.household_id is None:
        raise ProblemException(slug="forbidden", title="Kein aktiver Haushalt", status=403)
    return principal.household_id


def _entry_response(e: LedgerEntry) -> LedgerEntryResponse:
    return LedgerEntryResponse(
        id=e.id,
        from_account=e.from_account,
        to_account=e.to_account,
        amount=e.amount,
        ref_type=e.ref_type,
        ref_id=e.ref_id,
        note=e.note,
        created_at=e.created_at,
    )


@economy_router.get("/balance")
async def my_balance(principal: CurrentPrincipal, session: ScopedSession) -> BalanceResponse:
    _require_household(principal)
    bal = await service.balance(session, account=service.member_account(principal.user_id))
    return BalanceResponse(balance=bal)


@economy_router.get("/ledger")
async def my_ledger(
    principal: CurrentPrincipal,
    session: ScopedSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LedgerEntryResponse]:
    _require_household(principal)
    entries = await service.list_member_entries(session, user_id=principal.user_id, limit=limit)
    return [_entry_response(e) for e in entries]


@economy_router.post(
    "/corrections", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def post_correction(
    payload: CorrectionRequest, principal: AdminPrincipal, session: ScopedSession
) -> BalanceResponse:
    """Admin grants/claws back points with a visible counter-entry (KONZEPT §5.9). Returns the
    member's new balance. A claw-back below zero is refused (422)."""
    household_id = _require_household(principal)
    await service.admin_correction(
        session,
        household_id=household_id,
        admin_id=principal.user_id,
        member_id=payload.member_id,
        amount=payload.amount,
        note=payload.note,
    )
    bal = await service.balance(session, account=service.member_account(payload.member_id))
    return BalanceResponse(balance=bal)


def _reward_response(r: Reward) -> RewardResponse:
    return RewardResponse(
        id=r.id,
        title=r.title,
        description=r.description,
        cost=r.cost,
        stock=r.stock,
        cooldown_hours=r.cooldown_hours,
        kind=r.kind,
        active=r.active,
        version=r.version,
    )


def _redemption_response(r: Redemption) -> RedemptionResponse:
    return RedemptionResponse(
        id=r.id,
        reward_id=r.reward_id,
        member_id=r.member_id,
        title=r.title,
        cost=r.cost,
        status=r.status,
        created_at=r.created_at,
    )


# --- Rewards catalog ---------------------------------------------------------


@economy_router.get("/rewards")
async def list_rewards(principal: CurrentPrincipal, session: ScopedSession) -> list[RewardResponse]:
    _require_household(principal)
    rewards = await service.list_rewards(session, include_inactive=principal.role == Role.admin)
    return [_reward_response(r) for r in rewards]


@economy_router.post(
    "/rewards", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def create_reward(
    payload: RewardCreate, principal: AdminPrincipal, session: ScopedSession, response: Response
) -> RewardResponse:
    household_id = _require_household(principal)
    reward = await service.create_reward(session, household_id=household_id, data=payload)
    response.headers["ETag"] = f'"{reward.version}"'
    return _reward_response(reward)


@economy_router.get("/rewards/{reward_id}")
async def get_reward(
    reward_id: uuid.UUID,
    principal: CurrentPrincipal,
    session: ScopedSession,
    response: Response,
) -> RewardResponse:
    _require_household(principal)
    reward = await service.get_reward(session, reward_id=reward_id)
    response.headers["ETag"] = f'"{reward.version}"'
    return _reward_response(reward)


@economy_router.patch("/rewards/{reward_id}", dependencies=[Depends(require_csrf)])
async def update_reward(
    reward_id: uuid.UUID,
    payload: RewardUpdate,
    request: Request,
    principal: AdminPrincipal,
    session: ScopedSession,
    response: Response,
) -> RewardResponse:
    household_id = _require_household(principal)
    expected = parse_if_match(request.headers.get("if-match"))
    reward = await service.update_reward(
        session,
        household_id=household_id,
        reward_id=reward_id,
        expected_version=expected,
        data=payload,
    )
    response.headers["ETag"] = f'"{reward.version}"'
    return _reward_response(reward)


@economy_router.delete(
    "/rewards/{reward_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
async def delete_reward(
    reward_id: uuid.UUID, principal: AdminPrincipal, session: ScopedSession
) -> None:
    household_id = _require_household(principal)
    await service.delete_reward(session, household_id=household_id, reward_id=reward_id)


@economy_router.post(
    "/rewards/{reward_id}/redeem",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
async def redeem_reward(
    reward_id: uuid.UUID, principal: CurrentPrincipal, session: ScopedSession
) -> RedemptionResponse:
    """Redeem a reward for points (any household member). Debits the cost (coverage-checked),
    decrements stock, enforces cooldown, and records a ``requested`` redemption."""
    household_id = _require_household(principal)
    redemption = await service.redeem_reward(
        session, household_id=household_id, reward_id=reward_id, member_id=principal.user_id
    )
    return _redemption_response(redemption)


# --- Redemptions -------------------------------------------------------------


@economy_router.get("/redemptions")
async def list_redemptions(
    principal: CurrentPrincipal,
    session: ScopedSession,
    status_filter: Annotated[
        Literal["requested", "fulfilled", "all"], Query(alias="status")
    ] = "all",
) -> list[RedemptionResponse]:
    """Admins see the whole household (confirm list); members see their own redemptions."""
    _require_household(principal)
    redemptions = await service.list_redemptions(
        session,
        user_id=principal.user_id,
        all_members=principal.role == Role.admin,
        status=None if status_filter == "all" else status_filter,
    )
    return [_redemption_response(r) for r in redemptions]


@economy_router.post("/redemptions/{redemption_id}/fulfill", dependencies=[Depends(require_csrf)])
async def fulfill_redemption(
    redemption_id: uuid.UUID, principal: AdminPrincipal, session: ScopedSession
) -> RedemptionResponse:
    """Admin confirms a redemption was handed out in the real world (``requested -> fulfilled``)."""
    household_id = _require_household(principal)
    redemption = await service.fulfil_redemption(
        session, household_id=household_id, redemption_id=redemption_id
    )
    return _redemption_response(redemption)


# --- Thanks + weekly challenge -----------------------------------------------


@economy_router.post(
    "/thanks", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)]
)
async def send_thanks(
    payload: ThanksRequest, principal: CurrentPrincipal, session: ScopedSession
) -> ThanksResponse:
    """Send thank-you points to another member (member -> member, coverage-checked + weekly cap)."""
    household_id = _require_household(principal)
    remaining = await service.send_thanks(
        session,
        household_id=household_id,
        from_user=principal.user_id,
        to_user=payload.to_member_id,
        amount=payload.amount,
        note=payload.note,
    )
    return ThanksResponse(remaining_this_week=remaining)


@economy_router.get("/challenge")
async def weekly_challenge(
    principal: CurrentPrincipal, session: ScopedSession
) -> ChallengeResponse:
    """Weekly challenge standings (points earned from task completions this ISO week) + the caller's
    remaining thank-you allowance. Computed live from the ledger (no stored counter)."""
    _require_household(principal)
    standings = await service.weekly_challenge(session)
    given = await service.thanks_given_this_week(session, user_id=principal.user_id)
    return ChallengeResponse(
        standings=[ChallengeStanding(member_id=uid, points=pts) for uid, pts in standings],
        thanks_remaining=service.THANKS_WEEKLY_CAP - given,
    )


@economy_router.get("/fairness")
async def fairness(principal: CurrentPrincipal, session: ScopedSession) -> FairnessResponse:
    """Fairness account (KONZEPT §5.9): each member's load (points earned from task completions over
    the rolling window), lowest first — least carried = next in line. Live from the ledger."""
    _require_household(principal)
    loads = await service.fairness_load(session)
    entries = sorted(
        (FairnessEntry(member_id=uid, load=load) for uid, load in loads.items()),
        key=lambda e: e.load,
    )
    return FairnessResponse(window_days=service.FAIRNESS_WINDOW_DAYS, entries=entries)
