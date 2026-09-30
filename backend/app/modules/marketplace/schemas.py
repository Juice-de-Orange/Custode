"""HTTP request/response contracts for ``marketplace`` (single source for the OpenAPI schema -> web
zod client). Separate from the ORM models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ListingStatus = Literal["open", "accepted", "settled", "reverted", "withdrawn"]


class ListingCreate(BaseModel):
    """List one of your own open task instances for sale at ``price`` points."""

    task_instance_id: uuid.UUID
    price: int = Field(ge=1, le=100000)


class ListingResponse(BaseModel):
    id: uuid.UUID
    task_instance_id: uuid.UUID
    title: str
    seller_id: uuid.UUID
    price: int
    status: ListingStatus
    buyer_id: uuid.UUID | None
    created_at: datetime


class AutoAcceptRuleCreate(BaseModel):
    """A standing rule: auto-accept listings of ``template_id`` (or any) up to ``max_price``."""

    template_id: uuid.UUID | None = None
    max_price: int = Field(ge=1, le=100000)


class AutoAcceptRuleResponse(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    template_id: uuid.UUID | None
    max_price: int
    active: bool
