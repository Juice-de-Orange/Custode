"""Transactional mail of the accounts module: password reset and e-mail verification.

Every mail exists in German and English with the same content; the recipient's stored
``users.locale`` picks the language (:func:`app.kernel.ports.mail.mail_language` — German for a
German locale, English for everything else). Plain text: the SMTP adapter sends the body as is."""

from __future__ import annotations

from app.kernel.ports.mail import MailLanguage, mail_language

_PASSWORD_RESET: dict[MailLanguage, tuple[str, str]] = {
    "de": (
        "Passwort zurücksetzen",
        "Hallo,\n\n"
        "zum Zurücksetzen deines Passworts öffne diesen Link (eine Stunde gültig):\n\n"
        "{link}\n\n"
        "Wenn du das nicht angefordert hast, kannst du diese E-Mail ignorieren.\n",
    ),
    "en": (
        "Reset your password",
        "Hello,\n\n"
        "to reset your password, open this link (valid for one hour):\n\n"
        "{link}\n\n"
        "If you did not ask for this, you can ignore this e-mail.\n",
    ),
}

_VERIFICATION: dict[MailLanguage, tuple[str, str]] = {
    "de": (
        "E-Mail bestätigen",
        "Hallo,\n\n"
        "bitte bestätige deine E-Mail-Adresse über diesen Link (24 Stunden gültig):\n\n"
        "{link}\n\n"
        "Wenn du kein Konto angelegt hast, kannst du diese E-Mail ignorieren.\n",
    ),
    "en": (
        "Confirm your e-mail address",
        "Hello,\n\n"
        "please confirm your e-mail address with this link (valid for 24 hours):\n\n"
        "{link}\n\n"
        "If you did not create an account, you can ignore this e-mail.\n",
    ),
}


def _render(
    templates: dict[MailLanguage, tuple[str, str]], locale: str | None, link: str
) -> tuple[str, str]:
    subject, body = templates[mail_language(locale)]
    return subject, body.format(link=link)


def password_reset_mail(locale: str | None, link: str) -> tuple[str, str]:
    """(subject, body) of the password-reset mail in the recipient's language."""
    return _render(_PASSWORD_RESET, locale, link)


def verification_mail(locale: str | None, link: str) -> tuple[str, str]:
    """(subject, body) of the e-mail-verification mail in the recipient's language."""
    return _render(_VERIFICATION, locale, link)
