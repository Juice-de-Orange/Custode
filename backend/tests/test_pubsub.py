"""Per-household invalidation pub/sub. The publish->subscribe roundtrip, channel isolation
(a subscriber sees only its own household's hints — the live mirror of RLS), and keep-alive
idle ticks run against a Testcontainers Redis (``redis_db``). The Redis-down null path and
the invalidation-bridge mapping are pure (monkeypatched) and run anywhere."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest

from app.kernel.events.envelope import EventEnvelope
from app.kernel.events.handlers import invalidation_bridge
from app.kernel.events.pubsub import channel_for, publish_hint, subscribe_hints
from app.kernel.http.sse import InvalidationHint


async def _wait_subscribed(household_id: uuid.UUID, *, attempts: int = 100) -> None:
    """Poll until the subscriber is registered (pub/sub does not buffer, so we must publish
    only after the subscription is live)."""
    from app.kernel.redis import get_redis

    chan = channel_for(household_id)
    for _ in range(attempts):
        numsub = await get_redis().pubsub_numsub(chan)
        if numsub and int(numsub[0][1]) >= 1:
            return
        await asyncio.sleep(0.02)
    raise AssertionError("subscriber not registered in time")


async def _close(gen: AsyncIterator[InvalidationHint | None], task: asyncio.Task) -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await gen.aclose()


async def test_publish_subscribe_roundtrip(redis_db: None) -> None:
    h = uuid.uuid4()
    gen = subscribe_hints(h, keepalive_s=5.0)

    async def _first() -> InvalidationHint | None:
        async for item in gen:
            if item is not None:
                return item
        return None

    task: asyncio.Task[InvalidationHint | None] = asyncio.create_task(_first())
    try:
        await _wait_subscribed(h)
        await publish_hint(h, InvalidationHint(entity="members", id=str(h), version=1))
        hint = await asyncio.wait_for(task, timeout=5)
        assert hint == InvalidationHint(entity="members", id=str(h), version=1)
    finally:
        await _close(gen, task)


async def test_channel_isolation(redis_db: None) -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    gen = subscribe_hints(a, keepalive_s=0.2)

    async def _collect() -> InvalidationHint | None:
        idle = 0
        async for item in gen:
            if item is None:
                idle += 1
                if idle >= 2:  # two keep-alives seen, nothing leaked from B
                    return None
            else:
                return item  # a hint from B reached A's subscriber -> leak
        return None

    task: asyncio.Task[InvalidationHint | None] = asyncio.create_task(_collect())
    try:
        await _wait_subscribed(a)
        await publish_hint(b, InvalidationHint(entity="members", id=str(b), version=1))
        leaked = await asyncio.wait_for(task, timeout=5)
        assert leaked is None  # B's hint never reached A's subscriber
    finally:
        await _close(gen, task)


async def test_publish_swallows_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Null path: a Redis failure must not propagate to the outbox handler (no retry/DLQ)."""

    class _Boom:
        async def publish(self, *_a: object, **_k: object) -> None:
            from redis.exceptions import ConnectionError as RedisConnError

            raise RedisConnError("down")

    monkeypatch.setattr("app.kernel.events.pubsub.get_redis", lambda: _Boom())
    await publish_hint(uuid.uuid4(), InvalidationHint(entity="members", id="x", version=1))


async def test_invalidation_bridge_publishes_for_member_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[tuple[uuid.UUID, InvalidationHint]] = []

    async def _fake_publish(hid: uuid.UUID, hint: InvalidationHint) -> None:
        published.append((hid, hint))

    monkeypatch.setattr("app.kernel.events.handlers.publish_hint", _fake_publish)
    h = uuid.uuid4()
    env = EventEnvelope(type="member.joined", household_id=h, occurred_at=datetime.now(UTC))
    await invalidation_bridge(env)
    assert published == [(h, InvalidationHint(entity="members", id=str(h), version=1))]


async def test_invalidation_bridge_ignores_unmapped_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    published: list[object] = []

    async def _fake_publish(hid: uuid.UUID, hint: InvalidationHint) -> None:
        published.append((hid, hint))

    monkeypatch.setattr("app.kernel.events.handlers.publish_hint", _fake_publish)
    env = EventEnvelope(
        type="unmapped.event", household_id=uuid.uuid4(), occurred_at=datetime.now(UTC)
    )
    await invalidation_bridge(env)
    assert published == []
