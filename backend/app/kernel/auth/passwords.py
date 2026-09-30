"""Password hashing — Argon2id (KONZEPT §8, OWASP-empfohlene Parameter) — plus the
length policy. The HIBP pwned-check lives in ``pwned.py`` (network adapter)."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()

# NIST 800-63B: enforce a length floor, no composition rules. The upper bound is a
# DoS guard (Argon2 over arbitrarily large input).
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1024


def password_too_weak(password: str) -> str | None:
    """A user-facing (German) reason if the password violates the length policy,
    else None. Breached-password rejection is separate (``pwned.py``)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Passwort muss mindestens {MIN_PASSWORD_LENGTH} Zeichen lang sein."
    if len(password) > MAX_PASSWORD_LENGTH:
        return "Passwort ist zu lang."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
