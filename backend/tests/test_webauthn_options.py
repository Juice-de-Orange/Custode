"""Unit tests for the WebAuthn option builders (``kernel/auth/webauthn.py``) — pure, no DB, no
Redis. Both the member and the operator login are usernameless (``allowCredentials: []``), so a
credential that is not discoverable can be registered but never used to sign in."""

from __future__ import annotations

import json

from app.kernel.auth import webauthn


def test_registration_requires_a_discoverable_credential() -> None:
    options_json, _ = webauthn.registration_options(
        rp_id="localhost",
        rp_name="Custode",
        user_id=b"\x01" * 16,
        user_name="mira@example.com",
        exclude_ids=[],
    )
    selection = json.loads(options_json)["authenticatorSelection"]
    assert selection["residentKey"] == "required"
    # WebAuthn L1 clients only know the boolean; py-webauthn mirrors it for "required".
    assert selection["requireResidentKey"] is True


def test_authentication_is_usernameless() -> None:
    """The counterpart: this is WHY registration must ask for a discoverable credential."""
    options_json, _ = webauthn.authentication_options(rp_id="localhost", allow_ids=[])
    assert json.loads(options_json).get("allowCredentials", []) == []
