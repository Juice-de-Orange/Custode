"""notes — Notizen (household-scoped, +RLS) (KONZEPT §5 / Phase 7)

Revision ID: 0044_notes
Revises: 0043_recipe_cooked_history
Create Date: 2026-06-24

Phase 7, P7-S1: das manuelle Notizen-Fundament. ``notes`` = eine Markdown-Notiz je Haushalt
(``title`` + ``body_md``), optional ans Dashboard ``pinned``, mit ``author_id``. Household-scoped,
RLS ``household_isolation`` (USING + WITH CHECK) + FORCE, gemeinsamer Versions-Trigger (``version``
= ETag für PATCH + If-Match). Versions-Historie / „Konvertieren-zu" / Dashboard-Pin-Sicht folgen in
späteren Slices.
"""

from __future__ import annotations

from alembic import op

revision = "0044_notes"
down_revision = "0043_recipe_cooked_history"
branch_labels = None
depends_on = None


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
    op.execute(
        f"CREATE POLICY household_isolation ON {table} "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        f"""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO custode_app;
            END IF;
        END $$;
        """  # noqa: S608 — ``table`` is a hardcoded literal, not user input
    )
    op.execute(
        f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notes (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            author_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            body_md text NOT NULL DEFAULT '',
            pinned boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_notes_household_id ON notes (household_id);")
    # Partial index to list pinned notes cheaply (dashboard pin view, later slice).
    op.execute(
        "CREATE INDEX ix_notes_household_pinned ON notes (household_id) "
        "WHERE pinned AND deleted_at IS NULL;"
    )
    _rls("notes")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notes CASCADE;")
