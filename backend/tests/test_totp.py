"""TOTP unit tests (no infra). Validates the RFC 6238 implementation against the
published Appendix-B test vectors (SHA1, secret = ASCII "12345678901234567890"),
truncated to our 6 digits, plus drift window, rejection, and the otpauth URI."""

from __future__ import annotations

import base64

import pytest

from app.kernel.auth import totp

# RFC 6238 Appendix B (SHA1) 8-digit codes → our 6-digit = value % 1_000_000.
_RFC_SECRET = base64.b32encode(b"12345678901234567890").decode("ascii")


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (59, "287082"),  # 94287082
        (1111111109, "081804"),  # 07081804
        (1111111111, "050471"),  # 14050471
        (1234567890, "005924"),  # 89005924
        (2000000000, "279037"),  # 69279037
    ],
)
def test_rfc6238_vectors(at: int, expected: str) -> None:
    assert totp.now(_RFC_SECRET, at=at) == expected
    assert totp.verify(_RFC_SECRET, expected, at=at, window=0)


def test_roundtrip() -> None:
    secret = totp.generate_secret()
    assert totp.verify(secret, totp.now(secret))


def test_window_accepts_adjacent_step() -> None:
    secret = totp.generate_secret()
    prev = totp.now(secret, at=1000 - 30)
    assert totp.verify(secret, prev, at=1000, window=1)
    assert not totp.verify(secret, prev, at=1000, window=0)


def test_reject_invalid() -> None:
    secret = totp.generate_secret()
    assert not totp.verify(secret, "abcdef")
    assert not totp.verify(secret, "")
    assert not totp.verify(secret, "12345")  # too short
    assert not totp.verify(secret, "1234567")  # too long
    old = totp.now(secret, at=1000)
    assert not totp.verify(secret, old, at=1000 + 300, window=1)  # far in the past


def test_provisioning_uri() -> None:
    uri = totp.provisioning_uri("ABC234", account="a@b.de", issuer="Custode")
    assert uri.startswith("otpauth://totp/Custode:a%40b.de?")
    assert "secret=ABC234" in uri
    assert "issuer=Custode" in uri
    assert "period=30" in uri
