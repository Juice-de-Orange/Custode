"""SSE invalidation stream (`GET /v1/stream`). The auth gate (401) and the no-household
keep-alive are hermetic; the hint->``invalidate`` frame uses a Testcontainers Redis
(``redis_db``, skipped without Docker)."""

from __future__ import annotations

import asyncio
import contextlib
import uuid

from httpx import AsyncClient

from app.kernel.events.pubsub import channel_for, publish_hint
from app.kernel.http.sse import InvalidationHint
from app.kernel.http.stream import event_stream


async def test_stream_requires_auth(client: AsyncClient) -> None:
    # No access cookie -> the principal dependency 401s before any streaming starts.
    response = await client.get("/v1/stream")
    assert response.status_code == 401


async def test_event_stream_keepalive_without_household() -> None:
    gen = event_stream(None, keepalive_s=0.05)
    try:
        frame = await asyncio.wait_for(anext(gen), timeout=2)
        assert frame == ": ping\n\n"
    finally:
        await gen.aclose()


async def _wait_subscribed(household_id: uuid.UUID, *, attempts: int = 100) -> None:
    from app.kernel.redis import get_redis

    chan = channel_for(household_id)
    for _ in range(attempts):
        numsub = await get_redis().pubsub_numsub(chan)
        if numsub and int(numsub[0][1]) >= 1:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("subscriber not registered in time")


async def test_event_stream_emits_invalidate_frame_on_hint(redis_db: None) -> None:
    h = uuid.uuid4()
    gen = event_stream(h, keepalive_s=5.0)

    async def _first_invalidate() -> str | None:
        async for frame in gen:
            if frame.startswith("event: invalidate"):
                return frame
        return None

    task: asyncio.Task[str | None] = asyncio.create_task(_first_invalidate())
    try:
        await _wait_subscribed(h)
        await publish_hint(h, InvalidationHint(entity="members", id=str(h), version=1))
        frame = await asyncio.wait_for(task, timeout=5)
        assert frame is not None
        assert frame.startswith("event: invalidate\ndata: ")
        assert '"entity":"members"' in frame
        assert frame.endswith("\n\n")
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await gen.aclose()
