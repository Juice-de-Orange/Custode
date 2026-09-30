"""SSE invalidation hints (ADR-002). Events carry no payload — only
``{entity, id, version}``; the client refetches via the normal authorized API."""

from __future__ import annotations

from pydantic import BaseModel


class InvalidationHint(BaseModel):
    entity: str
    id: str
    version: int

    def to_sse(self) -> str:
        return f"event: invalidate\ndata: {self.model_dump_json()}\n\n"
