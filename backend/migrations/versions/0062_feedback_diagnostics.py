"""feedback.diagnostics — opt-in Diagnose-Anhang (KONZEPT §5.12)

Revision ID: 0062_feedback_diagnostics
Revises: 0061_ops_feedback_view
Create Date: 2026-06-30

Phase 8, P8-S5 (Rest): der Feedback-Kanal bekommt einen **strikt opt-in** Diagnose-Anhang —
App-Version + ein kleiner Ringpuffer der zuletzt gesehenen Fehler-Referenzcodes/Routen, **nie
Inhalte/PII**. Additive, nullable JSONB-Spalte; expand-only (kein Backfill). Die Betreiber-Inbox-
View ``ops_feedback`` (0061) wird um die Spalte erweitert, damit der Support den Kontext sieht —
weiterhin nur über die View, nie die Fachtabelle (ADR-0015).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0062_feedback_diagnostics"
down_revision = "0061_ops_feedback_view"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "feedback",
        sa.Column("diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Extend the operator inbox view with the new column. DROP + CREATE (a plain CREATE OR REPLACE
    # cannot always add columns to a view); re-set owner + grant exactly like 0061 so the
    # security-definer aggregation + ops_readonly SELECT keep working in prod (owner != superuser).
    op.execute("DROP VIEW IF EXISTS ops_feedback;")
    op.execute(
        """
        CREATE VIEW ops_feedback AS
        SELECT id, household_id, category, message, error_ref, route, diagnostics, created_at
        FROM feedback
        WHERE deleted_at IS NULL;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                GRANT CREATE ON SCHEMA public TO custode_maint;
                ALTER VIEW ops_feedback OWNER TO custode_maint;
                REVOKE CREATE ON SCHEMA public FROM custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON ops_feedback TO ops_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS ops_feedback;")
    op.execute(
        """
        CREATE VIEW ops_feedback AS
        SELECT id, household_id, category, message, error_ref, route, created_at
        FROM feedback
        WHERE deleted_at IS NULL;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                GRANT CREATE ON SCHEMA public TO custode_maint;
                ALTER VIEW ops_feedback OWNER TO custode_maint;
                REVOKE CREATE ON SCHEMA public FROM custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON ops_feedback TO ops_readonly;
            END IF;
        END $$;
        """
    )
    op.drop_column("feedback", "diagnostics")
