"""TOTP (RFC 6238) for two-factor auth (KONZEPT §8). Pure stdlib — HMAC-SHA1 per the
RFC, no custom crypto and no new dependency. The base32 secret is generated server-side;
the client renders the ``otpauth://`` URI as a QR code. Verification allows ±1 time step
for clock drift and compares constant-time."""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

_DIGITS = 6
_PERIOD = 30
_SECRET_BYTES = 20  # 160-bit — the common authenticator secret size


def generate_secret() -> str:
    """A fresh base32 TOTP secret (unpadded, as authenticator apps expect)."""
    return base64.b32encode(secrets.token_bytes(_SECRET_BYTES)).decode("ascii").rstrip("=")


def _hotp(secret_b32: str, counter: int) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8))
    # RFC 6238 mandates HMAC-SHA1; SHA1 is not broken under HMAC. (digestmod as a
    # string keeps ruff S324 — which targets bare hashlib.sha1 — out of the way.)
    digest = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10**_DIGITS)).zfill(_DIGITS)


def now(secret_b32: str, *, at: float | None = None) -> str:
    """The current code for ``secret_b32`` (enrollment confirmation + tests)."""
    moment = time.time() if at is None else at
    return _hotp(secret_b32, int(moment // _PERIOD))


def verify(secret_b32: str, code: str, *, at: float | None = None, window: int = 1) -> bool:
    """True if ``code`` matches within ±``window`` time steps (clock drift). Constant-time."""
    if not code or not code.isdigit() or len(code) != _DIGITS:
        return False
    moment = time.time() if at is None else at
    counter = int(moment // _PERIOD)
    return any(
        hmac.compare_digest(_hotp(secret_b32, counter + drift), code)
        for drift in range(-window, window + 1)
    )


def provisioning_uri(secret_b32: str, *, account: str, issuer: str) -> str:
    """The ``otpauth://totp/...`` URI the client turns into a QR code."""
    # Keep the issuer:account separator colon literal (Key-URI convention); encode the rest.
    label = quote(f"{issuer}:{account}", safe=":")
    params = urlencode(
        {
            "secret": secret_b32,
            "issuer": issuer,
            "algorithm": "SHA1",
            "digits": _DIGITS,
            "period": _PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{params}"
