"""notes — note_versions (Versions-Historie, household-scoped, +RLS) (KONZEPT §5)

Revision ID: 0045_note_versions
Revises: 0044_notes
Create Date: 2026-06-24

Phase 7, P7-S2: jede Notiz-Inhaltsänderung schreibt den **vorherigen** Stand als Snapshot in
``note_versions`` (Titel + Body + wer + wann). Pro Notiz werden nur die **letzten 5** behalten
(ältere werden beim Schreiben weggeschnitten). Household-scoped, RLS ``household_isolation``
(USING + WITH CHECK) + FORCE. Kein Versions-Trigger nötig (append-only).
"""

from __future__ import annotations

from alembic import op

revision = "0045_note_versions"
down_revision = "0044_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE note_versions (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            note_id uuid NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            version_no integer NOT NULL,
            title varchar(200) NOT NULL,
            body_md text NOT NULL,
            edited_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_note_versions_household_id ON note_versions (household_id);")
    op.execute(
        "CREATE UNIQUE INDEX uq_note_versions_note_version ON note_versions (note_id, version_no);"
    )
    op.execute("ALTER TABLE note_versions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE note_versions FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON note_versions "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON note_versions TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS note_versions CASCADE;")
