"""Lazy async Redis client. Nothing connects at import time, so the app boots and
exports OpenAPI without Redis — mirrors ``db/engine.py``. Redis backs short-lived
opaque access tokens (``kernel/auth/access.py``) and the readiness probe."""

from __future__ import annotations

import redis.asyncio as aioredis

from app.settings import get_settings

_redis: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Process-wide async Redis client (``decode_responses`` → ``str`` values)."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    """Dispose the client (lifespan shutdown + test reset). Idempotent."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
