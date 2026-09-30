from __future__ import annotations

from typing import Protocol

from fastapi import Request


class MailPort(Protocol):
    async def send(self, *, to: str, subject: str, body_md: str) -> bool: ...


def get_mail(request: Request) -> MailPort:
    """FastAPI dependency: the mail adapter chosen at startup (``app.state.mail``). Lives in the
    kernel so modules depend only on ``kernel/*`` — the concrete adapter is selected in the
    composition root (``main.py``); import-linter forbids ``modules``/``kernel`` → ``adapters``."""
    mail: MailPort = request.app.state.mail
    return mail
