"""WebAuthn (passkey) ceremony helpers — thin wrappers over py-webauthn (the crypto is
NOT hand-rolled, ADR-0023) plus a short-lived Redis challenge store. The relying-party id
and expected origin are derived from the request, so passkeys work on localhost and the
live domain without configuration; verification fails closed on an origin mismatch."""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlparse

import webauthn
from fastapi import Request
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
)

from app.kernel.redis import get_redis

_CHALLENGE_TTL_S = 300  # 5 min to complete a ceremony


def rp_from_request(request: Request) -> tuple[str, str]:
    """(rp_id, origin) derived from the request: ``origin`` prefers the browser-sent Origin
    header, ``rp_id`` is its hostname. Falls back to the request URL."""
    origin = request.headers.get("origin")
    if not origin:
        host = request.headers.get("host") or request.url.netloc
        origin = f"{request.url.scheme}://{host}"
    rp_id = urlparse(origin).hostname or "localhost"
    return rp_id, origin


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def canonical_id(value: str) -> str:
    """Normalise a client-sent credential id to unpadded base64url (matches storage)."""
    return _b64url(_unb64url(value))


async def put_challenge(key: str, challenge: bytes) -> None:
    await cast(
        "Awaitable[object]",
        get_redis().set(f"webauthn:{key}", _b64url(challenge), ex=_CHALLENGE_TTL_S),
    )


async def pop_challenge(key: str) -> bytes | None:
    """Single-use: return the stored challenge and delete it (or ``None`` if absent)."""
    redis = get_redis()
    raw = await cast("Awaitable[str | None]", redis.get(f"webauthn:{key}"))
    if raw is None:
        return None
    await redis.delete(f"webauthn:{key}")
    return _unb64url(raw)


@dataclass(frozen=True)
class RegisteredCredential:
    credential_id: str  # base64url
    public_key: str  # base64url of the COSE key
    sign_count: int
    transports: str | None


def registration_options(
    *, rp_id: str, rp_name: str, user_id: bytes, user_name: str, exclude_ids: list[str]
) -> tuple[str, bytes]:
    """Build registration (attestation) options; returns (options_json, challenge).

    The credential must be **discoverable** (resident key ``required``): both logins are
    usernameless (``authentication_options`` with empty ``allow_ids``), and an authenticator can
    only answer that with a credential it stored itself. ``preferred`` would let a key without
    free resident-key storage register a server-side credential that verifies fine here and
    can then never sign in — ``required`` makes that fail at registration, where the user sees it.
    """
    options = webauthn.generate_registration_options(
        rp_id=rp_id,
        rp_name=rp_name,
        user_name=user_name,
        user_id=user_id,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=_unb64url(c)) for c in exclude_ids],
    )
    return webauthn.options_to_json(options), options.challenge


def verify_registration(
    *, credential: dict[str, Any], challenge: bytes, rp_id: str, origin: str
) -> RegisteredCredential:
    verified = webauthn.verify_registration_response(
        credential=json.dumps(credential),
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
    )
    transports = None
    response = credential.get("response", {})
    if isinstance(response, dict) and response.get("transports"):
        transports = ",".join(response["transports"])[:120]
    return RegisteredCredential(
        credential_id=_b64url(verified.credential_id),
        public_key=_b64url(verified.credential_public_key),
        sign_count=verified.sign_count,
        transports=transports,
    )


def authentication_options(*, rp_id: str, allow_ids: list[str]) -> tuple[str, bytes]:
    """Build authentication (assertion) options; returns (options_json, challenge).
    ``allow_ids`` empty → discoverable-credential (passwordless) login."""
    options = webauthn.generate_authentication_options(
        rp_id=rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=_unb64url(c)) for c in allow_ids],
    )
    return webauthn.options_to_json(options), options.challenge


def verify_authentication(
    *,
    credential: dict[str, Any],
    challenge: bytes,
    rp_id: str,
    origin: str,
    public_key: str,
    sign_count: int,
) -> int:
    """Verify an assertion against the stored public key; returns the new sign count."""
    verified = webauthn.verify_authentication_response(
        credential=json.dumps(credential),
        expected_challenge=challenge,
        expected_rp_id=rp_id,
        expected_origin=origin,
        credential_public_key=_unb64url(public_key),
        credential_current_sign_count=sign_count,
    )
    return int(verified.new_sign_count)
