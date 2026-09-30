"""Weekly-digest composition + fan-out (Roadmap Phase 8, „Week-Digest"). A logic-only module: no
table, no router — the worker's weekly cron calls :func:`send_weekly_digests` under the **maint
role** (it spans households, ARCHITECTURE §9). Cross-module data comes **only** through public apis
(``accounts.api`` for recipients, ``tasks.api`` for the open-task counts), never foreign tables.

Graceful Enhancement (P5): the send goes through ``MailPort``. With the Null adapter nothing is
sent and the app is unaffected; with SMTP each adult member gets the summary. No PII in logs."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.kernel.ports.mail import MailPort
from app.modules.accounts import api as accounts_api
from app.modules.tasks import api as tasks_api


def _compose(
    brand: str, household_name: str, open_count: int, overdue_count: int
) -> tuple[str, str]:
    """Build the (subject, markdown body) of a household's weekly digest. German, calm, no PII —
    only aggregate counts of the household's own state."""
    subject = f"{brand}: Wochenüberblick für {household_name}"
    if open_count == 0:
        tasks_line = "Alle Aufgaben sind erledigt — schöne Woche!"
    elif overdue_count == 0:
        tasks_line = f"Offene Aufgaben: {open_count}."
    else:
        tasks_line = f"Offene Aufgaben: {open_count} (davon {overdue_count} überfällig)."
    body = (
        f"Hallo,\n\n"
        f"hier ist der Wochenüberblick für **{household_name}**.\n\n"
        f"- {tasks_line}\n\n"
        f"Plant eure Woche in Ruhe in {brand}.\n"
    )
    return subject, body


async def send_weekly_digests(
    session: AsyncSession, *, mail: MailPort, brand: str, now: datetime
) -> int:
    """Compose and send the weekly digest to every adult member of every household that has not
    opted out (``settings_json['digest_enabled']``, default on). ``session`` is a maint session.
    Returns the number of e-mails the mail adapter accepted (the Null adapter accepts but transmits
    nothing — the graceful base path)."""
    targets = await accounts_api.list_digest_recipients(session)
    sent = 0
    for target in targets:
        if not target.settings_json.get("digest_enabled", True):
            continue
        if not target.recipient_emails:
            continue
        open_count, overdue_count = await tasks_api.count_open_tasks(
            session, household_id=target.household_id, now=now
        )
        subject, body = _compose(brand, target.name, open_count, overdue_count)
        for email in target.recipient_emails:
            if await mail.send(to=email, subject=subject, body_md=body):
                sent += 1
    return sent
