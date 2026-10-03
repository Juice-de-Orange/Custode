"""The worker's broker must survive an idle queue (BUGLOG 2026-10-03).

``ListQueueBroker.listen`` blocks in ``BRPOP … 0``. redis-py 8 introduced a default
``socket_timeout`` of 5 s, which turned every idle period longer than that into a
``TimeoutError`` that killed the taskiq worker child — every five seconds, in dev and prod, while
the container stayed "healthy". Nothing in the suite noticed, because no test ever listened on the
real broker for longer than a moment. This one does: against a real Redis (Testcontainers), idle
for longer than redis-py's default, then a kicked message must still arrive.
"""

from __future__ import annotations

import asyncio
from typing import Any

from redis.asyncio.connection import DEFAULT_SOCKET_TIMEOUT
from taskiq.message import BrokerMessage

from app.worker import broker as worker_broker
from app.worker import build_broker


def test_module_broker_is_built_without_a_read_timeout() -> None:
    """The broker the worker actually runs — not just the factory — carries the setting."""
    assert worker_broker.connection_pool.connection_kwargs["socket_timeout"] is None


async def test_listen_survives_idle_longer_than_default_socket_timeout(redis_server: Any) -> None:
    host = redis_server.get_container_host_ip()
    port = redis_server.get_exposed_port(6379)
    broker = build_broker(f"redis://{host}:{port}/1")
    listener = broker.listen()
    try:
        # asyncio.Task needs a coroutine; __anext__ only returns an awaitable.
        async def _next() -> bytes:
            return await anext(listener)

        first = asyncio.ensure_future(_next())
        # Idle past the default: before the fix the pending BRPOP raised TimeoutError right here.
        done, _ = await asyncio.wait({first}, timeout=DEFAULT_SOCKET_TIMEOUT + 2)
        assert not done, f"listen() ended while idle: {first.exception()!r}"

        await broker.kick(
            BrokerMessage(task_id="t1", task_name="app.worker:ping", message=b"hello", labels={})
        )
        assert await asyncio.wait_for(first, timeout=5) == b"hello"
    finally:
        await listener.aclose()
        await broker.shutdown()
