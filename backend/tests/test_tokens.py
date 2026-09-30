"""Opaque-token unit tests (no DB): tokens are unique + high-entropy, and the
stored hash is a deterministic SHA-256 hex that never equals the token."""

from __future__ import annotations

from app.kernel.auth.tokens import hash_token, new_token


def test_new_token_is_unique_and_long() -> None:
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100  # no collisions
    assert all(len(t) >= 40 for t in tokens)  # 32 bytes url-safe ~ 43 chars


def test_hash_token_is_deterministic_sha256() -> None:
    token = new_token()
    digest = hash_token(token)
    assert digest == hash_token(token)
    assert len(digest) == 64  # sha256 hex
    assert digest != token
    assert all(c in "0123456789abcdef" for c in digest)
