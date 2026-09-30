"""Pure unit tests for the server-side credential encryption (ADR-0077). No Docker:
the box is deterministic crypto around a settings-provided key."""

from __future__ import annotations

import os

import pytest

from app.kernel.crypto import (
    SecretBox,
    SecretBoxError,
    generate_key,
    get_secretbox,
    require_secretbox,
)
from app.kernel.http.problem import ProblemException
from app.settings import get_settings


@pytest.fixture
def box() -> SecretBox:
    return SecretBox(generate_key())


def test_roundtrip(box: SecretBox) -> None:
    value = box.encrypt("s3cret-app-password")
    assert value.startswith("v1:")
    assert "s3cret" not in value
    assert box.decrypt(value) == "s3cret-app-password"


def test_roundtrip_unicode(box: SecretBox) -> None:
    plaintext = "pässwörd-→-☂"
    assert box.decrypt(box.encrypt(plaintext)) == plaintext


def test_ciphertexts_are_nondeterministic(box: SecretBox) -> None:
    # Fernet embeds a random IV — equal plaintexts must not produce equal rows.
    assert box.encrypt("same") != box.encrypt("same")


def test_tampered_value_rejected(box: SecretBox) -> None:
    value = box.encrypt("secret")
    tampered = value[:-2] + ("AA" if not value.endswith("AA") else "BB")
    with pytest.raises(SecretBoxError):
        box.decrypt(tampered)


def test_wrong_key_rejected(box: SecretBox) -> None:
    other = SecretBox(generate_key())
    with pytest.raises(SecretBoxError):
        other.decrypt(box.encrypt("secret"))


def test_unknown_scheme_rejected(box: SecretBox) -> None:
    with pytest.raises(SecretBoxError):
        box.decrypt("v2:whatever")
    with pytest.raises(SecretBoxError):
        box.decrypt("gAAAA-raw-fernet-without-prefix")


def test_malformed_key_fails_loud() -> None:
    with pytest.raises(ValueError):
        SecretBox("not-a-key")


def test_get_secretbox_none_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTODE_CRYPTO_KEY", raising=False)
    get_settings.cache_clear()
    try:
        assert get_secretbox() is None
        with pytest.raises(ProblemException) as excinfo:
            require_secretbox()
        assert excinfo.value.status == 503
    finally:
        get_settings.cache_clear()


def test_get_secretbox_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    key = generate_key()
    monkeypatch.setenv("CUSTODE_CRYPTO_KEY", key)
    get_settings.cache_clear()
    try:
        active = get_secretbox()
        assert active is not None
        assert require_secretbox().decrypt(active.encrypt("x")) == "x"
    finally:
        os.environ.pop("CUSTODE_CRYPTO_KEY", None)
        get_settings.cache_clear()
