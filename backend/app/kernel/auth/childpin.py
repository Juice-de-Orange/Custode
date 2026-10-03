"""Child PIN-login rate limiting (KONZEPT §8: child logins are rate-limited). A small Redis
counter per (household, username) locks the account after a few wrong PINs, so a 4-6 digit PIN
cannot be brute-forced. Keyed by household+username (never the PIN); no PII is stored."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import cast

from app.kernel.redis import get_redis

_MAX_FAILURES = 5
_LOCKOUT_S = 60 * 15  # 15 minutes


def _key(household_id: object, username: str) -> str:
    return f"child_pin_fail:{household_id}:{username}"


async def is_locked(household_id: object, username: str) -> bool:
    """True once too many consecutive wrong PINs have accumulated (within the lockout window)."""
    raw = await cast("Awaitable[str | None]", get_redis().get(_key(household_id, username)))
    return raw is not None and int(raw) >= _MAX_FAILURES


async def record_failure(household_id: object, username: str) -> None:
    """Count a wrong-PIN attempt; the first one starts the lockout window."""
    redis = get_redis()
    key = _key(household_id, username)
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, _LOCKOUT_S)


async def reset(household_id: object, username: str) -> None:
    """Clear the failure counter after a successful login."""
    await get_redis().delete(_key(household_id, username))
