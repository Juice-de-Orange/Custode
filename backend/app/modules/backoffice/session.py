"""Opaque Redis-backed operator sessions for the Betreiber-Konsole. Separate keyspace from the user
access tokens (``ops_session:<hash>``) — the ops console is its own auth stack (ADR-0015). Only the
SHA-256 hash is stored (a Redis dump yields no usable token). Bearer token (no ambient cookie, so no
CSRF surface); the ops backend is on its own ``/ops`` prefix/subdomain."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable
from typing import cast

from app.kernel.auth.tokens import hash_token, new_token
from app.kernel.redis import get_redis
from app.settings import get_settings


def _key(token_hash: str) -> str:
    return f"ops_session:{token_hash}"


async def mint_ops_session(operator_id: uuid.UUID) -> str:
    """Issue a fresh opaque operator-session token (TTL ``ops_session_ttl_s``)."""
    token = new_token()
    await cast(
        "Awaitable[object]",
        get_redis().set(
            _key(hash_token(token)), str(operator_id), ex=get_settings().ops_session_ttl_s
        ),
    )
    return token


async def load_ops_session(token: str) -> uuid.UUID | None:
    """Resolve a token to its operator id, or ``None`` (unknown/expired/Redis down). Fail-closed."""
    try:
        raw = await cast("Awaitable[str | None]", get_redis().get(_key(hash_token(token))))
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


async def revoke_ops_session(token: str) -> None:
    """Drop a single operator session (logout)."""
    await cast("Awaitable[int]", get_redis().delete(_key(hash_token(token))))
