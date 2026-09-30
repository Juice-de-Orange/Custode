"""Opaque token generation + hashing for sessions (KONZEPT §8.5).

Tokens are high-entropy random strings; only their SHA-256 hash is stored, so a DB
leak never yields a usable token. SHA-256 (not Argon2) is correct here: the token
already carries 256 bits of entropy, so there is nothing to brute-force — unlike a
human password."""

from __future__ import annotations

import hashlib
import secrets

_TOKEN_BYTES = 32


def new_token() -> str:
    """A fresh opaque token (URL-safe, ~43 chars, 256 bits of entropy)."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex of ``token`` — the value stored and looked up."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
