"""HTTP contracts for ``scheduling`` (single source for the OpenAPI schema -> web zod client)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SlotResponse(BaseModel):
    """One suggested free slot. ``reasons`` are machine-readable codes (e.g. ``no_conflict``,
    ``within_work_hours``) the web maps to localised plain-text justification (KONZEPT §5.12)."""

    start: datetime
    end: datetime
    reasons: list[str]
