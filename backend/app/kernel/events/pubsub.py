"""Per-household invalidation pub/sub over Redis (ARCHITECTURE §7, ADR-002).

The outbox handler (``handlers.py``) publishes an :class:`InvalidationHint` to
``hints:{household_id}``; the SSE endpoint (S4) subscribes to the active household's channel
and streams hints to that household's connected clients. Hints carry no payload — only
``{entity, id, version}`` — so the client just refetches via the normal authorized API.
Channel-per-household is the live mirror of RLS: a subscriber only ever sees its own
household's hints.

Redis is an accelerator, not a source of truth. If it is unreachable, ``publish_hint`` is a
logged no-op (the DB change already happened) and ``subscribe_hints`` ends quietly — the app
stays correct, just without push (clients fall back to refetch-on-focus)."""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncIterator

from redis.exceptions import RedisError

from app.kernel.http.sse import InvalidationHint
from app.kernel.redis import get_redis
from app.logging import get_logger

_log = get_logger("events.pubsub")


def channel_for(household_id: uuid.UUID) -> str:
    """The Redis pub/sub channel carrying a household's invalidation hints."""
    return f"hints:{household_id}"


async def publish_hint(household_id: uuid.UUID, hint: InvalidationHint) -> None:
    """Publish an invalidation hint to the household's channel. Best-effort: a Redis failure
    is logged (no PII — entity name only) and swallowed, so the caller (an outbox handler)
    still counts as delivered and never dead-letters on a transient Redis blip."""
    try:
        await get_redis().publish(channel_for(household_id), hint.model_dump_json())
    except RedisError:
        _log.warning("hint_publish_failed", household_id=str(household_id), entity=hint.entity)


async def subscribe_hints(
    household_id: uuid.UUID, *, keepalive_s: float = 20.0
) -> AsyncIterator[InvalidationHint | None]:
    """Yield invalidation hints for ``household_id``. Yields ``None`` after ``keepalive_s``
    idle seconds so the SSE layer can emit a keep-alive ping. Ends on a Redis failure; always
    cleans up the subscription on exit."""
    pubsub = get_redis().pubsub()
    try:
        await pubsub.subscribe(channel_for(household_id))
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=keepalive_s)
            if message is None:
                yield None  # idle tick -> the SSE layer emits a keep-alive
                continue
            data = message.get("data")
            if data is None:
                continue
            try:
                yield InvalidationHint.model_validate_json(data)
            except ValueError:
                _log.warning("hint_decode_failed", household_id=str(household_id))
    except RedisError:
        _log.warning("hint_subscribe_failed", household_id=str(household_id))
    finally:
        with contextlib.suppress(RedisError):
            await pubsub.aclose()  # type: ignore[no-untyped-call]  # redis stub gap
