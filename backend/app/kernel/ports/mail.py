from __future__ import annotations

from typing import Literal, Protocol

from fastapi import Request

#: The languages transactional mail is written in. Every template exists in each of them.
MailLanguage = Literal["de", "en"]


class MailPort(Protocol):
    #: False for the Null adapter (no SMTP host configured): nothing ever leaves the server, so
    #: the API must not claim a mail was sent (``mail_unavailable``, ``MeResponse.mail_enabled``).
    enabled: bool

    async def send(self, *, to: str, subject: str, body_md: str) -> bool: ...


def mail_language(locale: str | None) -> MailLanguage:
    """The language to write a recipient's mail in, from their stored ``users.locale``.

    German for any German tag (``de``, ``de-AT``, ``de_CH``); English for everything else,
    including a locale we have no templates for and a missing one."""
    tag = (locale or "").strip().lower().replace("_", "-")
    return "de" if tag.split("-")[0] == "de" else "en"


def get_mail(request: Request) -> MailPort:
    """FastAPI dependency: the mail adapter chosen at startup (``app.state.mail``). Lives in the
    kernel so modules depend only on ``kernel/*`` — the concrete adapter is selected in the
    composition root (``main.py``); import-linter forbids ``modules``/``kernel`` → ``adapters``."""
    mail: MailPort = request.app.state.mail
    return mail
