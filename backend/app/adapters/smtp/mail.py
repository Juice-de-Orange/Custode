"""SMTP mail adapter (ADR-0027). Sends transactional e-mail via ``aiosmtplib`` against
the operator's SMTP provider (prod, implicit TLS on :465 or STARTTLS on :587) or mailpit (dev).
Best-effort: a send failure is logged with a reference code (never the recipient or content)
and returned as ``False``, so the triggering operation stays consistent — the e-mail is an
enhancement, not a barrier (graceful degradation)."""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from app.logging import get_logger
from app.settings import Settings

_log = get_logger("adapters.smtp")


class SmtpMail:
    """Mail port implementation backed by an SMTP server (see module docstring)."""

    def __init__(self, settings: Settings) -> None:
        self._s = settings

    async def send(self, *, to: str, subject: str, body_md: str) -> bool:
        message = EmailMessage()
        # Display name from the brand constant (never hardcoded); envelope address from config.
        message["From"] = f"{self._s.brand_name} <{self._s.smtp_from}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body_md)  # plain text — the markdown source reads fine as-is
        try:
            await aiosmtplib.send(
                message,
                hostname=self._s.smtp_host,
                port=self._s.smtp_port,
                username=self._s.smtp_user or None,
                password=self._s.smtp_password or None,
                start_tls=self._s.smtp_starttls,
                use_tls=self._s.smtp_port == 465,  # implicit TLS on the SMTPS port
            )
            return True
        except Exception:
            # Never break the caller on a mail failure; no PII (recipient/subject/body) in logs.
            _log.warning("smtp_send_failed", ref="MAIL-SEND")
            return False
