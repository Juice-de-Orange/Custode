"""Idempotency-Key dependency (ADR-011). Every POST carries a client UUID;
the server stores the response snapshot 48h so retries are safe. Phase 0 exposes
the dependency; the snapshot store lands with the write paths in Phase 1+."""

from __future__ import annotations

from typing import Annotated

from fastapi import Header


async def idempotency_key(
    value: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str | None:
    return value
