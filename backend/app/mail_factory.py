"""Mail-adapter factory (ADR-0027). Shared by the API (`app/main.py`) and the worker
(`app/worker.py`) so both pick the same adapter from settings: real SMTP when a host is configured
(dev: mailpit; prod: the operator's SMTP provider), else the Null adapter (e-mail disabled, the
app still works)."""

from __future__ import annotations

from app.adapters.null import NullMail
from app.adapters.smtp.mail import SmtpMail
from app.kernel.ports.mail import MailPort
from app.settings import Settings


def build_mail(settings: Settings) -> MailPort:
    if settings.smtp_host:
        return SmtpMail(settings)
    return NullMail()
