"""capture — captures (household-scoped, +RLS) (KONZEPT §5.17)

Revision ID: 0030_captures
Revises: 0029_auto_accept_rules
Create Date: 2026-06-23

Zuruf-Basis (P4-S9a): ``captures`` — der Quick-Capture-Eingang. Ein Freitext-Zuruf wird vom offline
Regel-Parser in ``proposal_json`` zerlegt und landet als ``proposed`` in der Inbox; per Triage wird
er ``confirmed`` (Posten/Task angelegt) oder ``dismissed``. Household-scoped, RLS
``household_isolation`` (USING+WITH CHECK), gemeinsamer ``set_updated_and_version``-Trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0030_captures"
down_revision = "0029_auto_accept_rules"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE captures (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid NOT NULL,
            raw_text text NOT NULL,
            tags text[] NOT NULL DEFAULT '{}',
            status text NOT NULL DEFAULT 'proposed'
                CHECK (status IN ('proposed', 'confirmed', 'dismissed', 'auto')),
            proposal_json jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_captures_household_id ON captures (household_id);")
    op.execute("CREATE INDEX ix_captures_member_id ON captures (member_id);")
    op.execute(
        "CREATE TRIGGER trg_captures_updated BEFORE UPDATE ON captures "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE captures ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE captures FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON captures "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON captures TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS captures CASCADE;")
