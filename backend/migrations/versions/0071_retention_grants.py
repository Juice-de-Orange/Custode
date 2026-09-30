"""retention — die fehlenden maint-Rechte für die Tabellen im Reaper (Fix, BUGLOG 2026-07-31)

Der tägliche Reaper (``worker.reap_deleted_job``, Cron 03:00) läuft unter ``custode_maint`` über
``_RETENTION_TABLES``. Seit Phase 9 stehen dort drei Tabellen, aber nur ``notes`` hatte je die
nötigen Rechte (Migration 0053):

* ``external_calendar_subscriptions`` — ``maint_all``-Policy ja (0065), aber nur ``GRANT SELECT``
* ``calendar_events``                 — weder Policy noch irgendein Grant für maint (0032)

Postgres prüft Tabellenrechte beim **Planen**, nicht beim Treffer. Der Job scheiterte also jede
Nacht mit ``permission denied``, unabhängig davon, ob überhaupt Zeilen fällig waren — und weil alle
Tabellen in einer Transaktion liefen, riss der Fehler den ``notes``-Purge mit. Ergebnis: seit
Phase 9 wurde nichts mehr hart gelöscht, während die Datenschutzerklärung dem Nutzer sagt, dass
gelöschte Inhalte nach 30 Tagen endgültig entfernt werden.

Diese Migration ergänzt je Tabelle **genau das, was fehlt** — nicht mehr, damit der Downgrade nicht
die Arbeit von 0065 mit zurücknimmt. Die zweite Hälfte des Fixes ist ein Test, der die Liste gegen
die echte Datenbank prüft, statt sie zu glauben (``tests/test_retention_grants.py``): die Ursache
war eine Liste, die behauptet statt beweist.

Revision ID: 0071_retention_grants
Revises: 0070_wearable_retention
"""

from __future__ import annotations

from alembic import op

revision = "0071_retention_grants"
down_revision = "0070_wearable_retention"
branch_labels = None
depends_on = None

# Je Tabelle: braucht sie noch die ``maint_all``-Policy? Die Abos haben sie seit 0065, die Events
# gar nicht. ``notes`` ist seit 0053 vollständig versorgt und steht deshalb nicht hier.
_NEEDS_POLICY = {
    "external_calendar_subscriptions": False,
    "calendar_events": True,
}


def _guarded(body: str) -> str:
    """Alles nur, wenn die Rolle existiert — in dev/CI wird sie manchmal nicht angelegt (Muster
    aus 0053/0065)."""
    # S608: ``body`` wird aus den Tabellennamen des Literals ``_NEEDS_POLICY`` gebaut, nie aus
    # einer Eingabe — dieselbe Begründung wie in 0053/0065. Tabellennamen lassen sich in Postgres
    # nicht binden.
    return (
        "DO $$ BEGIN "  # noqa: S608
        "IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN "
        f"{body} "
        "END IF; END $$;"
    )


def upgrade() -> None:
    for table, needs_policy in _NEEDS_POLICY.items():
        statements = []
        if needs_policy:
            statements.append(
                f"EXECUTE 'CREATE POLICY maint_all ON {table} TO custode_maint "
                f"USING (true) WITH CHECK (true)';"
            )
        # SELECT ist bei den Abos schon da; ein wiederholtes GRANT ist ein No-Op, DELETE ist neu.
        statements.append(f"GRANT SELECT, DELETE ON {table} TO custode_maint;")
        op.execute(_guarded(" ".join(statements)))


def downgrade() -> None:
    for table, added_policy in _NEEDS_POLICY.items():
        statements = [f"REVOKE DELETE ON {table} FROM custode_maint;"]
        if added_policy:
            # Nur zurücknehmen, was DIESE Migration angelegt hat: bei den Abos stammen Policy und
            # SELECT aus 0065 und bleiben stehen.
            statements.append(f"REVOKE SELECT ON {table} FROM custode_maint;")  # noqa: S608
            statements.append(f"DROP POLICY IF EXISTS maint_all ON {table};")
        op.execute(_guarded(" ".join(statements)))
