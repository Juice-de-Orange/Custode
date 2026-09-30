"""HTTP request/response contracts for ``capture`` (single source for the OpenAPI schema -> web zod
client). ``ParsedProposal`` doubles as the persisted ``proposal_json`` shape."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ProposalTarget = Literal["shopping", "task", "note", "none"]
CaptureStatus = Literal["proposed", "confirmed", "dismissed", "auto"]


class FollowUp(BaseModel):
    """An action-chain follow-up task (KONZEPT §5.17 Deo-Fall): when the primary is a shopping item,
    a ``dann …``/``then …`` clause becomes a task armed on that item being checked."""

    label: str


class ParsedProposal(BaseModel):
    """The deterministic parser's result — what the Zuruf is understood to mean. ``target=none`` is
    an „Unsortiert"-capture (no buy verb, no forcing hint) that needs manual triage."""

    target: ProposalTarget
    label: str
    qty: str | None = None
    unit: str | None = None
    assignee_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    when: str | None = None
    follow_up: FollowUp | None = None


class CaptureCreate(BaseModel):
    """A free-text Zuruf. The server parses it; the client never sends a pre-parsed proposal."""

    raw_text: str = Field(min_length=1, max_length=500)


class CaptureResponse(BaseModel):
    id: uuid.UUID
    raw_text: str
    status: CaptureStatus
    tags: list[str]
    proposal: ParsedProposal
    created_at: datetime
