"""OAuth ``state`` handling (P9-S5, ADR-0081).

``state`` is the CSRF defence of the Authorization-Code flow and, because the callback arrives
as an unauthenticated top-level GET, also the thing that binds the callback back to the user who
started it. It therefore carries the whole pending decision (which member, which household,
which consent types) — the callback must not trust anything from the query string except the
code.

Same handling as the e-mail-verification and WebAuthn-challenge tokens: high-entropy value, only
its SHA-256 hash stored, short TTL, single-use. Storing the hash means a Redis dump does not
yield usable states; single-use means a replayed callback cannot mint a second connection.

Ten minutes is deliberately short — it is the time between clicking "connect" and finishing the
provider's consent screen, not a session.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from app.kernel.auth.tokens import hash_token, new_token
from app.kernel.redis import get_redis

_TTL_S = 600  # 10 minutes: long enough for a consent screen, short enough to matter


def _key(token_hash: str) -> str:
    return f"wearable_oauth:{token_hash}"


@dataclass(frozen=True)
class PendingConnect:
    """What the callback needs to know, none of which may come from the query string."""

    user_id: uuid.UUID
    household_id: uuid.UUID
    provider: str
    consent_types: list[str]


async def issue_state(pending: PendingConnect) -> str:
    """Mint a state token, store the pending decision under its hash (10 min TTL), return it."""
    token = new_token()
    payload = json.dumps(
        {
            "user_id": str(pending.user_id),
            "household_id": str(pending.household_id),
            "provider": pending.provider,
            "consent_types": pending.consent_types,
        }
    )
    await cast("Awaitable[object]", get_redis().set(_key(hash_token(token)), payload, ex=_TTL_S))
    return token


async def pop_state(token: str) -> PendingConnect | None:
    """Resolve **and delete** a state token (single-use). ``None`` when unknown, expired, already
    used, or malformed — the caller treats all of those identically, so a replay is
    indistinguishable from an expiry and leaks nothing.

    ``GETDEL`` (one round trip, Redis 6.2+) rather than GET-then-DELETE: with two commands, two
    callbacks arriving together both read the payload before either deletes it, and "single-use"
    silently becomes "usable twice" — precisely the guarantee this function exists for
    (BUGLOG 2026-07-30)."""
    redis = get_redis()
    key = _key(hash_token(token))
    raw = await cast("Awaitable[str | None]", redis.getdel(key))
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return PendingConnect(
            user_id=uuid.UUID(data["user_id"]),
            household_id=uuid.UUID(data["household_id"]),
            provider=str(data["provider"]),
            consent_types=[str(t) for t in data["consent_types"]],
        )
    except (KeyError, TypeError, ValueError):
        return None
