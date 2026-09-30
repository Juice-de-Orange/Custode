"""Domain-event envelope (ARCHITECTURE §8.2). Payloads are versioned; handlers
tolerate unknown fields (forward-compatibility)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.kernel.db.ids import new_uuid7


class EventEnvelope(BaseModel):
    id: uuid.UUID = Field(default_factory=new_uuid7)
    type: str
    version: int = 1
    household_id: uuid.UUID
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
