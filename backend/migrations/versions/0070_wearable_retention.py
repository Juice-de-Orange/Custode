"""wearables — DELETE-Grant für den Retention-Job (KONZEPT §11, Art. 9)

Revision ID: 0070_wearable_retention
Revises: 0069_wearables
Create Date: 2026-07-27

Phase 9, 9-S6. 0069 hat ``custode_maint`` bewusst nur SELECT gegeben (Least Privilege pro Slice):
der Ingest-Cron zählt auf, schreibt aber pro Mitglied unter ``scoped_session``. Der 90-Tage-
Retention-Job ist der erste Pfad, der wirklich haushaltsübergreifend **löschen** muss — pro
Mitglied zu scopen wäre hier sinnlos, weil er nichts über einzelne Mitglieder wissen muss.

Nur ``wearable_daily``: Rohwerte altern aus. ``wearable_connections`` bleibt bestehen, bis der
Mensch selbst trennt — eine Verbindung ist kein Messwert.

Bewusst **kein** Eintrag in ``_RETENTION_TABLES`` (app/worker.py): jener Reaper purgt
getombstete Zeilen (`deleted_at IS NOT NULL`), und beide Wearable-Tabellen verbieten Tombstones
per CHECK (ADR-0081). Die Wearable-Retention hat eine andere Achse — Alter des **Messtags**, nicht
Alter der Löschmarkierung — und darum einen eigenen Job.
"""

from __future__ import annotations

from alembic import op

revision = "0070_wearable_retention"
down_revision = "0069_wearables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                GRANT DELETE ON wearable_daily TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                REVOKE DELETE ON wearable_daily FROM custode_maint;
            END IF;
        END $$;
        """
    )
