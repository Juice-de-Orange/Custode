"""Password-reset tokens (KONZEPT §8). A single-use, 1-hour token lives in Redis as a
SHA-256 hash → user_id; the clear-text token is only ever in the e-mail. Mirrors the
access/refresh handling (hash-at-rest, TTL) — a Redis dump never yields a usable token."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable
from typing import cast

from app.kernel.auth.tokens import hash_token
from app.kernel.redis import get_redis

_TTL_S = 3600  # 1 hour


def _key(token_hash: str) -> str:
    return f"pwd_reset:{token_hash}"


async def issue_reset_token(user_id: uuid.UUID) -> str:
    """Mint a reset token for ``user_id``, store its hash (1 h TTL), return the clear token."""
    token = secrets.token_urlsafe(32)
    await cast(
        "Awaitable[object]", get_redis().set(_key(hash_token(token)), str(user_id), ex=_TTL_S)
    )
    return token


async def consume_reset_token(token: str) -> uuid.UUID | None:
    """Resolve + delete a reset token (single-use). Returns the user id, or ``None`` if the token
    is unknown/expired/malformed."""
    redis = get_redis()
    key = _key(hash_token(token))
    raw = await cast("Awaitable[str | None]", redis.get(key))
    if raw is None:
        return None
    await redis.delete(key)
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None
