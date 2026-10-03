"""Tests for the operator provisioning CLI (ADR-0015/0072).

The console is fail-closed on TOTP, so a provisioning path that forgets the secret produces an
account nobody can log into. These pin the parts that matter without a database.
"""

from __future__ import annotations

import pytest

from app.kernel.auth import totp
from app.scripts.create_operator import _PASSWORD_ENV, _generate_password, _valid_email, main


def test_generated_password_is_long_and_unique() -> None:
    first, second = _generate_password(), _generate_password()
    assert len(first) >= 24
    assert first != second


def test_generated_totp_secret_verifies() -> None:
    """A secret that does not verify would lock the operator out on first login."""
    secret = totp.generate_secret()
    assert totp.verify(secret, totp.now(secret))


def test_provisioning_uri_carries_issuer_and_account() -> None:
    uri = totp.provisioning_uri(totp.generate_secret(), account="ops@example.org", issuer="Custode")
    assert uri.startswith("otpauth://totp/")
    assert "ops%40example.org" in uri or "ops@example.org" in uri
    assert "issuer=Custode" in uri


def test_refuses_to_run_in_prod_without_the_ops_actions_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Falling back to custode_app would write the row with the wrong role and quietly undermine
    the operator boundary — the script must refuse, not improvise."""
    from app.settings import get_settings

    monkeypatch.setenv("CUSTODE_ENV", "production")
    monkeypatch.delenv("CUSTODE_DATABASE_URL_OPS_ACTIONS", raising=False)
    monkeypatch.setenv(_PASSWORD_ENV, "irrelevant")
    monkeypatch.setattr("sys.argv", ["create_operator", "ops@example.org"])
    get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize(
    "email", ["not-an-email", "ops@", "@example.org", "ops@a@example.org", "o ps@example.org", ""]
)
def test_refuses_an_address_that_is_not_an_email(
    email: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``create_operator not-an-email`` used to create the operator and print credentials for a
    login name nobody can have meant. It must stop before it touches the database."""

    def _must_not_run(*_a: object, **_k: object) -> None:
        raise AssertionError("the script reached the database with an invalid address")

    monkeypatch.setattr("app.scripts.create_operator._run", _must_not_run)
    monkeypatch.setattr("sys.argv", ["create_operator", email])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "E-Mail" in capsys.readouterr().err


def test_accepts_ordinary_addresses() -> None:
    assert _valid_email("ops@example.org")
    assert _valid_email("  First.Last+ops@mail.example.co.uk ")
    assert _valid_email("ops@localhost")  # a login name on a LAN host, not a deliverable address
