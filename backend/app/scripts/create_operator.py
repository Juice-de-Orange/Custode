"""Provision an operator for the Betreiber-Konsole (ADR-0015/0072).

There is deliberately **no self-serve signup** for operators — the console spans households, so
an account there cannot be created by anyone who merely has a browser. Until now that meant
provisioning was documented as "CLI/Seed" while no CLI existed, which turned the first login on
a fresh deployment into a hand-written SQL session. This is that CLI.

Usage (on the deployment host)::

    docker compose -f docker-compose.prod.yml run --rm api \\
        python -m app.scripts.create_operator ops@example.org

The password is read from ``CUSTODE_OPERATOR_PASSWORD`` or generated; the TOTP secret is always
generated. Both are printed **once** — TOTP is mandatory for the console (fail-closed), so an
operator without an enrolled secret cannot log in at all.

Idempotent by e-mail: a re-run reports the existing operator and changes nothing, so it is safe
to put in a runbook.

Runs on the ``ops_actions`` role (the only one that may write ops-owned tables) — the same
session the console's own writes use.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys

from sqlalchemy import select

from app.kernel.auth import totp
from app.kernel.db.engine import get_ops_actions_sessionmaker
from app.modules.backoffice.models import Operator
from app.modules.backoffice.service import create_operator
from app.settings import get_settings

_PASSWORD_ENV = "CUSTODE_OPERATOR_PASSWORD"  # noqa: S105 - env var NAME, not a secret


def _generate_password() -> str:
    """A long random password — this account guards cross-household access, and nobody has to
    type it from memory (it goes into a password manager)."""
    return secrets.token_urlsafe(24)


async def _run(email: str, password: str) -> int:
    settings = get_settings()
    factory = get_ops_actions_sessionmaker()
    async with factory() as session, session.begin():
        existing = await session.scalar(
            select(Operator).where(Operator.email == email.strip().lower())
        )
        if existing is not None:
            print(f"Operator {email} existiert bereits (id={existing.id}) — nichts geändert.")
            return 0
        secret = totp.generate_secret()
        operator = await create_operator(
            session, email=email, password=password, totp_secret=secret
        )

    uri = totp.provisioning_uri(secret, account=email, issuer=settings.brand_name)
    print("Operator angelegt.")
    print(f"  id:       {operator.id}")
    print(f"  E-Mail:   {email}")
    print(f"  Passwort: {password}")
    print(f"  TOTP:     {secret}")
    print(f"  QR-URI:   {uri}")
    print()
    print("Diese Werte erscheinen NUR JETZT — in einen Passwortmanager übernehmen und den")
    print("TOTP-Eintrag sofort in der Authenticator-App anlegen. Ohne TOTP ist kein Login")
    print("möglich (die Konsole ist fail-closed).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Operator für die Betreiber-Konsole anlegen")
    parser.add_argument("email", help="E-Mail-Adresse des Operators")
    args = parser.parse_args()

    settings = get_settings()
    # Read straight from the environment: this is a one-off provisioning input, not
    # app configuration, so it has no business in Settings.
    password = os.environ.get(_PASSWORD_ENV) or _generate_password()
    if settings.env != "dev" and not settings.database_url_ops_actions:
        # Falling back to custode_app here would write the row with the wrong role and quietly
        # undermine the operator boundary (ADR-0071) — refuse instead.
        print(
            "CUSTODE_DATABASE_URL_OPS_ACTIONS ist nicht gesetzt. Ohne die ops_actions-Rolle "
            "wuerde dieser Schreibvorgang auf custode_app zurueckfallen und die "
            "Betreiber-Grenze unterlaufen. Bitte zuerst die Rolle einrichten "
            "(siehe .env.prod.example und docker-compose.prod.yml).",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_run(args.email, password)))


if __name__ == "__main__":
    main()
