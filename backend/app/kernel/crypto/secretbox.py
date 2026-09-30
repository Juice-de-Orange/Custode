"""Server-side secret encryption for third-party credentials (ADR-0077).

The vault is client-side E2E — the server never sees plaintext. Integrations are the
opposite case: CalDAV subscription passwords and wearable OAuth tokens must be usable
BY the server (the sync worker authenticates with them), so the server encrypts them
at rest instead of hashing. Scheme: Fernet (AES-128-CBC + HMAC-SHA256, authenticated,
versioned tokens) from ``cryptography``; the key comes from ``CUSTODE_CRYPTO_KEY`` and
lives only in the deployment ``.env`` (never in the repo, never in the DB).

Stored values carry a ``v1:`` scheme prefix so a later algorithm/key rotation can
recognise and re-wrap old rows. Without a configured key the dependent features are
simply off (factories fall back to Null adapters, endpoints answer 503) — Graceful
Enhancement, never a crash. Plaintext secrets must never be logged (root CLAUDE.md).
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.kernel.http.problem import ProblemException
from app.settings import get_settings

_SCHEME_PREFIX = "v1:"


class SecretBoxError(Exception):
    """Decryption failed: tampered value, wrong key, or unknown scheme. Deliberately
    carries no payload details (the ciphertext could be attacker-controlled)."""


def generate_key() -> str:
    """A fresh urlsafe-base64 Fernet key for ``CUSTODE_CRYPTO_KEY`` (ops helper)."""
    return Fernet.generate_key().decode("ascii")


class SecretBox:
    """Symmetric encrypt/decrypt for short credential strings."""

    def __init__(self, key: str) -> None:
        # Raises ValueError on a malformed key — fail loud at composition time,
        # not at the first encrypt.
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return _SCHEME_PREFIX + self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value.startswith(_SCHEME_PREFIX):
            raise SecretBoxError("unknown scheme")
        try:
            return self._fernet.decrypt(value[len(_SCHEME_PREFIX) :].encode("ascii")).decode(
                "utf-8"
            )
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise SecretBoxError("invalid token") from exc


def get_secretbox() -> SecretBox | None:
    """The box for the configured key, or ``None`` when credential encryption is off
    (``CUSTODE_CRYPTO_KEY`` unset). Callers treat ``None`` as "feature unavailable"."""
    key = get_settings().crypto_key
    return SecretBox(key) if key else None


def require_secretbox() -> SecretBox:
    """The box, or a 503 problem when the deployment has no crypto key — the same
    fail-closed shape the blob storage uses for an unconfigured backend."""
    box = get_secretbox()
    if box is None:
        raise ProblemException(
            slug="crypto_unconfigured",
            title="Verschlüsselung nicht konfiguriert",
            status=503,
            detail="Diese Funktion braucht einen Server-Schlüssel (CUSTODE_CRYPTO_KEY). "
            "Bitte den Betreiber kontaktieren.",
        )
    return box
