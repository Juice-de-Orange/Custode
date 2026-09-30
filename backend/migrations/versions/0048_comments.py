"""comments — Kommentare an Objekten (household-scoped, +RLS) (KONZEPT §5.12)

Revision ID: 0048_comments
Revises: 0047_guides
Create Date: 2026-06-24

Phase 7, P7-S7: generische Kommentare/Threads an beliebigen Objekten (Rezept, Task, Event, Liste,
Anleitung): ``comments`` mit ``object_type`` (String-Diskriminator) + ``object_id`` (nacktes UUID,
kein modulübergreifender FK) + ``author_id`` + ``body_md``. Household-scoped, RLS
``household_isolation`` (USING + WITH CHECK) + FORCE, gemeinsamer Versions-Trigger. @-Mentions +
Notification-Fan-out folgen in späteren Slices.
"""

from __future__ import annotations

from alembic import op

revision = "0048_comments"
down_revision = "0047_guides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE comments (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            object_type varchar(40) NOT NULL,
            object_id uuid NOT NULL,
            author_id uuid NOT NULL,
            body_md text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_comments_household_id ON comments (household_id);")
    # The hot lookup is "all comments on this object" — index the discriminator pair.
    op.execute(
        "CREATE INDEX ix_comments_object ON comments (object_type, object_id) "
        "WHERE deleted_at IS NULL;"
    )
    op.execute("ALTER TABLE comments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE comments FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON comments "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON comments TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_comments_updated BEFORE UPDATE ON comments "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS comments CASCADE;")
