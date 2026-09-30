"""Opaque, short-lived access tokens backed by Redis (KONZEPT §8.5).

The session's long-lived half (rotating refresh) lives in Postgres (``auth_sessions``);
this is the short-lived half: an opaque token whose SHA-256 hash keys a Redis entry
holding the request principal (user, active household, role) for ``access_token_ttl_s``.
Only the hash is stored, so a Redis dump never yields a usable token — same rationale as
the refresh hash (``kernel/auth/tokens.py``). Tokens are revoked individually (logout,
rotation) or per login *family* (theft signal), via a family index set."""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import cast

from app.kernel.auth.context import Role
from app.kernel.auth.tokens import hash_token, new_token
from app.kernel.redis import get_redis
from app.settings import get_settings


@dataclass(frozen=True, slots=True)
class AccessClaims:
    """The principal carried by an access token (mirrors ``Principal``)."""

    user_id: uuid.UUID
    household_id: uuid.UUID | None
    role: Role | None
    family_id: uuid.UUID


def _access_key(token_hash: str) -> str:
    return f"access:{token_hash}"


def _family_key(family_id: uuid.UUID) -> str:
    return f"access_family:{family_id}"


def _active_key(family_id: uuid.UUID) -> str:
    return f"active_household:{family_id}"


async def mint_access(
    *,
    user_id: uuid.UUID,
    household_id: uuid.UUID | None,
    role: Role | None,
    family_id: uuid.UUID,
) -> str:
    """Issue a fresh opaque access token for ``family_id`` and index it under the
    family, so a theft-revoke can burn every access token of that login at once."""
    token = new_token()
    token_hash = hash_token(token)
    payload = json.dumps(
        {
            "user_id": str(user_id),
            "household_id": str(household_id) if household_id is not None else None,
            "role": role.value if role is not None else None,
            "family_id": str(family_id),
        }
    )
    settings = get_settings()
    redis = get_redis()
    await cast(
        "Awaitable[object]",
        redis.set(_access_key(token_hash), payload, ex=settings.access_token_ttl_s),
    )
    await cast("Awaitable[int]", redis.sadd(_family_key(family_id), token_hash))
    await cast(
        "Awaitable[bool]", redis.expire(_family_key(family_id), settings.refresh_token_ttl_s)
    )
    return token


async def load_access(token: str) -> AccessClaims | None:
    """Resolve a token to its claims, or ``None`` (unknown/expired/parse error/Redis
    down). Fail-closed: any failure means "no session" so the caller answers 401."""
    try:
        raw = await cast("Awaitable[str | None]", get_redis().get(_access_key(hash_token(token))))
    except Exception:
        return None
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        household = data["household_id"]
        role = data["role"]
        return AccessClaims(
            user_id=uuid.UUID(data["user_id"]),
            household_id=uuid.UUID(household) if household is not None else None,
            role=Role(role) if role is not None else None,
            family_id=uuid.UUID(data["family_id"]),
        )
    except (KeyError, ValueError, TypeError):
        return None


async def revoke_access(token: str) -> None:
    """Drop a single access token (logout, or the consumed token on rotation)."""
    await cast("Awaitable[int]", get_redis().delete(_access_key(hash_token(token))))


async def _drop_family_tokens(family_id: uuid.UUID) -> None:
    """Delete the family's access tokens and its index set — but nothing else."""
    redis = get_redis()
    members = await cast("Awaitable[set[str]]", redis.smembers(_family_key(family_id)))
    if members:
        await cast("Awaitable[int]", redis.delete(*[_access_key(h) for h in members]))
    await cast("Awaitable[int]", redis.delete(_family_key(family_id)))


async def revoke_access_family(family_id: uuid.UUID) -> None:
    """Burn every access token of a login family + its bookkeeping (theft / logout).

    Räumt auch den gemerkten Haushalt ab: die Sitzung ist beendet, es gibt nichts mehr
    fortzuschreiben."""
    await _drop_family_tokens(family_id)
    await cast("Awaitable[int]", get_redis().delete(_active_key(family_id)))


async def revoke_access_tokens(family_id: uuid.UUID) -> None:
    """Nur die Access-Tokens entwerten — die Sitzung **bleibt**, der gemerkte Haushalt auch.

    Für Fälle, in denen sich nicht der Zugang ändert, sondern die **Rechte**: nach einem
    Rollenwechsel ist die Person weiterhin Mitglied desselben Haushalts, nur mit einer anderen
    Rolle. Die nächste Anfrage antwortet 401, der Client rotiert still, und ``refresh`` leitet
    Haushalt und Rolle frisch aus der Datenbank ab.

    ``revoke_access_family`` wäre hier das falsche Werkzeug: es löscht zusätzlich
    ``active_household:<family>``, und damit stünde die Person nach einer Herabstufung ohne
    Haushalts-Kontext da — zurückgeworfen in die Auswahl, obwohl sich an ihrer Mitgliedschaft
    nichts geändert hat."""
    await _drop_family_tokens(family_id)


async def set_active_household(
    family_id: uuid.UUID, household_id: uuid.UUID | None, role: Role | None
) -> None:
    """Remember the active household for a login family so ``refresh`` can carry it
    forward even after the access token expired. ``None`` clears it."""
    redis = get_redis()
    if household_id is None or role is None:
        await cast("Awaitable[int]", redis.delete(_active_key(family_id)))
        return
    payload = json.dumps({"household_id": str(household_id), "role": role.value})
    await cast(
        "Awaitable[object]",
        redis.set(_active_key(family_id), payload, ex=get_settings().refresh_token_ttl_s),
    )


async def get_active_household(family_id: uuid.UUID) -> tuple[uuid.UUID, Role] | None:
    """The active household (id, role) for a login family, or ``None``."""
    try:
        raw = await cast("Awaitable[str | None]", get_redis().get(_active_key(family_id)))
    except Exception:
        return None
    if raw is None:
        return None
    try:
        data = json.loads(raw)
        return uuid.UUID(data["household_id"]), Role(data["role"])
    except (KeyError, ValueError, TypeError):
        return None
