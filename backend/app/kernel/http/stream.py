"""SSE stream of per-household invalidation hints (ARCHITECTURE §7, ADR-002).

``GET /v1/stream`` is a long-lived ``text/event-stream``: the client (an ``EventSource``)
connects once per session and receives ``event: invalidate`` frames when its active household
changes, then refetches via the normal authorized API. The stream is scoped strictly to the
caller's active household — the same one the access token carries — so there is no second
authorization path (ADR-002). A keep-alive comment every ~20 s stops idle proxies from
dropping the connection.

Not in the OpenAPI schema: the web uses ``EventSource`` directly (not the generated client),
so keeping it out avoids a phantom client operation and a contract-diff break — like
``/healthz``. The fallback when this stream is unavailable is the normal refetch-on-focus
path (S5)."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.kernel.auth.dependencies import CurrentPrincipal
from app.kernel.events.pubsub import subscribe_hints

router = APIRouter(tags=["stream"])

_KEEPALIVE = ": ping\n\n"  # SSE comment — ignored by clients, keeps the connection warm
_KEEPALIVE_S = 20.0


async def event_stream(
    household_id: uuid.UUID | None, *, keepalive_s: float = _KEEPALIVE_S
) -> AsyncIterator[str]:
    """Yield SSE frames for the household: an ``invalidate`` frame per hint, a keep-alive
    comment on every idle tick. With no active household, only keep-alives (the SPA always
    connects; it just has nothing to invalidate yet)."""
    if household_id is None:
        while True:
            await asyncio.sleep(keepalive_s)
            yield _KEEPALIVE
    else:
        async for hint in subscribe_hints(household_id, keepalive_s=keepalive_s):
            yield _KEEPALIVE if hint is None else hint.to_sse()


@router.get("/v1/stream", include_in_schema=False)
async def stream(principal: CurrentPrincipal) -> StreamingResponse:
    return StreamingResponse(
        event_stream(principal.household_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
