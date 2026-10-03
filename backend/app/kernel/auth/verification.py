"""E-mail verification tokens (KONZEPT §5.1). A single-use, 24-hour token lives in Redis as a
SHA-256 hash → user_id; the clear-text token is only ever in the e-mail. Mirrors the password-reset
handling (``kernel/auth/reset.py``): hash-at-rest, TTL, single-use."""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Awaitable
from typing import cast

from app.kernel.auth.tokens import hash_token
from app.kernel.redis import get_redis

_TTL_S = 60 * 60 * 24  # 24 hours


def _key(token_hash: str) -> str:
    return f"email_verify:{token_hash}"


async def issue_verification_token(user_id: uuid.UUID) -> str:
    """Mint a verification token for ``user_id``, store its hash (24 h TTL), return the token."""
    token = secrets.token_urlsafe(32)
    await cast(
        "Awaitable[object]", get_redis().set(_key(hash_token(token)), str(user_id), ex=_TTL_S)
    )
    return token


async def consume_verification_token(token: str) -> uuid.UUID | None:
    """Resolve + delete a verification token (single-use). Returns the user id, or ``None`` if the
    token is unknown/expired/malformed."""
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
