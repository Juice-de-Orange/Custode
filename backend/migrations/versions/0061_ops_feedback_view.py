"""ops_feedback — Betreiber-Inbox für Feedback-Einsendungen (ADR-0015)

Revision ID: 0061_ops_feedback_view
Revises: 0060_household_metadata
Create Date: 2026-06-29

Phase 8, P8-S8e: schließt die in P8-S5 angekündigte Schleife — der Betreiber liest die Feedback-
Einsendungen. Feedback ist ein **Kanal AN den Betreiber** (kein verstecktes Fachdatum), daher darf
die Konsole es sehen — aber wie alles Betreiberseitige über eine **View**, nie die Fachtabelle
direkt (ADR-0015). Wie die KPI-Views (0055): ``custode_maint`` erhält ``maint_all`` + SELECT auf
``feedback`` und besitzt die security-definer-View ``ops_feedback``; ``ops_readonly`` liest sie.
"""

from __future__ import annotations

from alembic import op

revision = "0061_ops_feedback_view"
down_revision = "0060_household_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Operator may read feedback across households (it is addressed to support). Additive to
    # household_isolation; custode_app stays household-scoped.
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON feedback TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT ON feedback TO custode_maint;
            END IF;
        END $$;
        """
    )
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


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS ops_feedback;")
    op.execute("DROP POLICY IF EXISTS maint_all ON feedback;")
