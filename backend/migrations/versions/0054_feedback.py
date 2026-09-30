"""feedback — Friends&Family-Feedback-Kanal (household-scoped, +RLS) (Roadmap Phase 8)

Revision ID: 0054_feedback
Revises: 0053_retention_maint
Create Date: 2026-06-29

Phase 8, P8-S5: in-App-Feedback (Bug/Idee/Lob/Sonstiges) mit Freitext, optionalem
Fehler-Referenzcode (ARCH §12) und Route. Household-scoped, RLS ``household_isolation``
(USING + WITH CHECK) + FORCE, gemeinsamer Versions-Trigger. Die Betreiber-Konsole liest später
(P8-S8) nur eine Aggregat-/Aktions-Sicht, nie diese Fachtabelle (ADR-015).
"""

from __future__ import annotations

from alembic import op

revision = "0054_feedback"
down_revision = "0053_retention_maint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feedback (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            author_id uuid NOT NULL,
            category varchar(20) NOT NULL,
            message text NOT NULL,
            error_ref varchar(64),
            route varchar(120),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_feedback_household_id ON feedback (household_id);")
    # The member's own-submissions list reads by author, newest first.
    op.execute(
        "CREATE INDEX ix_feedback_author ON feedback (author_id, created_at DESC) "
        "WHERE deleted_at IS NULL;"
    )
    op.execute("ALTER TABLE feedback ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE feedback FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON feedback "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON feedback TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_feedback_updated BEFORE UPDATE ON feedback "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feedback CASCADE;")
