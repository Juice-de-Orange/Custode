"""Unit tests for the CalDAV credential encoding (P9-S2, ADR-0077) — no Docker. The
encode/decode pair is the format contract between the write path and the 9-S3 pull-sync
worker; errors stay opaque like the SecretBox itself."""

from __future__ import annotations

import pytest

from app.kernel.crypto import SecretBox, SecretBoxError, generate_key
from app.modules.calendar.creds import decode_credentials, encode_credentials


def test_roundtrip_including_unicode() -> None:
    box = SecretBox(generate_key())
    value = encode_credentials(box, username="max@example.de", password="päss wörd ✓")
    assert value.startswith("v1:")
    assert "päss wörd ✓" not in value
    assert decode_credentials(box, value) == ("max@example.de", "päss wörd ✓")


def test_tampered_value_raises() -> None:
    box = SecretBox(generate_key())
    value = encode_credentials(box, username="u", password="p")
    tampered = value[:-2] + ("AA" if not value.endswith("AA") else "BB")
    with pytest.raises(SecretBoxError):
        decode_credentials(box, tampered)


def test_wrong_key_raises() -> None:
    value = encode_credentials(SecretBox(generate_key()), username="u", password="p")
    with pytest.raises(SecretBoxError):
        decode_credentials(SecretBox(generate_key()), value)


def test_non_credential_payload_raises() -> None:
    # A valid box value that is not the {username, password} JSON shape must fail opaquely too —
    # the decoder accepts exactly what the encoder produced, nothing else.
    box = SecretBox(generate_key())
    with pytest.raises(SecretBoxError):
        decode_credentials(box, box.encrypt("not json"))
    with pytest.raises(SecretBoxError):
        decode_credentials(box, box.encrypt('{"user": "x"}'))
