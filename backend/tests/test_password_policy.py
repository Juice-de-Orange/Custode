"""Password policy unit tests (no DB): length floor + HIBP pwned-check with a
mocked transport, including the graceful Null-Adapter path when HIBP is down."""

from __future__ import annotations

import hashlib

import httpx

from app.kernel.auth.passwords import MIN_PASSWORD_LENGTH, password_too_weak
from app.kernel.auth.pwned import pwned_count


def test_password_too_short() -> None:
    assert password_too_weak("x" * (MIN_PASSWORD_LENGTH - 1)) is not None


def test_password_acceptable_length() -> None:
    assert password_too_weak("ein-gutes-passphrase") is None


def test_password_too_long() -> None:
    assert password_too_weak("x" * 2000) is not None


def _hibp_transport(suffix_counts: dict[str, int]) -> httpx.MockTransport:
    body = "\r\n".join(f"{suffix}:{count}" for suffix, count in suffix_counts.items())

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=body)

    return httpx.MockTransport(handler)


def _suffix(password: str) -> str:
    return hashlib.sha1(password.encode(), usedforsecurity=False).hexdigest().upper()[5:]


async def test_pwned_detects_breached_password() -> None:
    password = "password123"  # test fixture, not a real secret
    transport = _hibp_transport({_suffix(password): 4242, "0" * 35: 1})
    async with httpx.AsyncClient(transport=transport) as client:
        assert await pwned_count(password, client=client) == 4242


async def test_pwned_clean_password_returns_zero() -> None:
    transport = _hibp_transport({"DEADBEEF" + "0" * 27: 9})
    async with httpx.AsyncClient(transport=transport) as client:
        assert await pwned_count("eine-sehr-eigene-passphrase-xyz", client=client) == 0


async def test_pwned_graceful_when_unreachable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        # Null-Adapter: unreachable HIBP -> None (caller proceeds, logs).
        assert await pwned_count("irgendein-passwort-123", client=client) is None
