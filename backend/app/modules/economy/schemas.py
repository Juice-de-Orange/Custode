"""HTTP request/response contracts for ``economy`` (single source for the OpenAPI schema -> web zod
client). Separate from the ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RewardKind = Literal["standard", "mealplan_wish", "custom"]
RedemptionStatus = Literal["requested", "fulfilled"]


class BalanceResponse(BaseModel):
    """A member's current points balance (a SUM over the ledger, never a stored field)."""

    balance: int


class LedgerEntryResponse(BaseModel):
    id: uuid.UUID
    from_account: str
    to_account: str
    amount: int
    ref_type: str
    ref_id: uuid.UUID | None
    note: str | None
    created_at: datetime


class CorrectionRequest(BaseModel):
    """Admin grant (amount > 0) or claw-back (amount < 0) of points for a member."""

    member_id: uuid.UUID
    amount: int = Field(ge=-100000, le=100000)
    note: str | None = Field(default=None, max_length=500)


class RewardCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    cost: int = Field(gt=0, le=100000)
    stock: int | None = Field(default=None, ge=0, le=100000)
    cooldown_hours: int | None = Field(default=None, ge=0, le=100000)
    kind: RewardKind = "standard"
    active: bool = True


class RewardUpdate(BaseModel):
    """Partial update (If-Match)."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    cost: int | None = Field(default=None, gt=0, le=100000)
    stock: int | None = Field(default=None, ge=0, le=100000)
    cooldown_hours: int | None = Field(default=None, ge=0, le=100000)
    kind: RewardKind | None = None
    active: bool | None = None


class RewardResponse(BaseModel):
    """A reward; ``version`` is the ETag for admin If-Match."""

    id: uuid.UUID
    title: str
    description: str | None
    cost: int
    stock: int | None
    cooldown_hours: int | None
    kind: RewardKind
    active: bool
    version: int


class RedemptionResponse(BaseModel):
    id: uuid.UUID
    reward_id: uuid.UUID
    member_id: uuid.UUID
    title: str
    cost: int
    status: RedemptionStatus
    created_at: datetime


class ThanksRequest(BaseModel):
    """Send thank-you points to another member (KONZEPT §5.9)."""

    to_member_id: uuid.UUID
    amount: int = Field(ge=1, le=100)
    note: str | None = Field(default=None, max_length=200)


class ThanksResponse(BaseModel):
    remaining_this_week: int  # the giver's remaining weekly thank-you allowance


class ChallengeStanding(BaseModel):
    member_id: uuid.UUID
    points: int


class ChallengeResponse(BaseModel):
    """Weekly challenge standings (points earned from task completions this ISO week), highest
    first, computed live from the ledger. ``thanks_remaining`` = caller's remaining weekly cap."""

    standings: list[ChallengeStanding]
    thanks_remaining: int


class FairnessEntry(BaseModel):
    member_id: uuid.UUID
    load: int  # points earned from task completions over the fairness window


class FairnessResponse(BaseModel):
    """Fairness account (KONZEPT §5.9): each member's load over the rolling window, lowest first
    (least carried = next in line). Computed live from the ledger; absence-exclusion = Phase 5."""

    window_days: int
    entries: list[FairnessEntry]
