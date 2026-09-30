"""Mail adapters (ADR-0027). The Null adapter is a no-op; the SMTP adapter builds a message and
is best-effort — a send failure returns ``False`` and never raises (graceful degradation). Pure:
no Docker, no real SMTP server (``aiosmtplib.send`` is mocked)."""

from __future__ import annotations

import pytest

from app.adapters.null import NullMail
from app.adapters.smtp.mail import SmtpMail
from app.settings import Settings


async def test_null_mail_is_noop() -> None:
    assert await NullMail().send(to="a@b.de", subject="x", body_md="y") is True


async def test_smtp_mail_sends_constructed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    async def _fake_send(message: object, **kwargs: object) -> None:
        captured["message"] = message

    monkeypatch.setattr("app.adapters.smtp.mail.aiosmtplib.send", _fake_send)
    settings = Settings(smtp_from="noreply@custode.test", brand_name="Custode")
    ok = await SmtpMail(settings).send(to="user@example.de", subject="Hallo", body_md="Text")
    assert ok is True
    message = captured["message"]
    assert message["To"] == "user@example.de"
    assert message["Subject"] == "Hallo"
    assert "Custode" in message["From"]
    assert "noreply@custode.test" in message["From"]


async def test_smtp_mail_swallows_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(message: object, **kwargs: object) -> None:
        raise ConnectionRefusedError("no smtp here")

    monkeypatch.setattr("app.adapters.smtp.mail.aiosmtplib.send", _boom)
    assert await SmtpMail(Settings()).send(to="a@b.de", subject="x", body_md="y") is False
