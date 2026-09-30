"""guides — Anleitungen (household-scoped, +RLS, deutsche FTS) (KONZEPT §5 / Phase 7)

Revision ID: 0047_guides
Revises: 0046_letters
Create Date: 2026-06-24

Phase 7, P7-S6: Anleitungen-Fundament. ``guides`` = eine Markdown-Anleitung je Haushalt (Titel +
Body + Kategorie + Tags). **Deutsche Volltextsuche** über eine GENERATED ``search_tsv`` (immutable
``to_tsvector('german', …)``) + GIN-Index. Household-scoped, RLS ``household_isolation`` (USING +
WITH CHECK) + FORCE, gemeinsamer Versions-Trigger (``version`` = ETag). Anhänge, ACL und
Ansprechpartner folgen in späteren Slices.
"""

from __future__ import annotations

from alembic import op

revision = "0047_guides"
down_revision = "0046_letters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE guides (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            author_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            body_md text NOT NULL DEFAULT '',
            category varchar(80) NOT NULL DEFAULT '',
            tags text[] NOT NULL DEFAULT '{}',
            search_tsv tsvector GENERATED ALWAYS AS (
                to_tsvector('german', coalesce(title, '') || ' ' || coalesce(body_md, ''))
            ) STORED,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_guides_household_id ON guides (household_id);")
    op.execute("CREATE INDEX ix_guides_search_tsv ON guides USING gin (search_tsv);")
    op.execute("ALTER TABLE guides ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE guides FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON guides "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON guides TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_guides_updated BEFORE UPDATE ON guides "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS guides CASCADE;")
