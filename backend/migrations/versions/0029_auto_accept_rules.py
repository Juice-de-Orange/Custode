"""marketplace — auto_accept_rules (household-scoped, +RLS) (KONZEPT §5.10)

Revision ID: 0029_auto_accept_rules
Revises: 0028_marketplace
Create Date: 2026-06-23

Auto-Accept (P4-S8b): ``auto_accept_rules`` — ein Mitglied pflegt Regeln „Task-Typ X bis Preis Y
automatisch annehmen". Matcht ein neues Listing, wird sofort zugeschlagen; bei mehreren Treffern
entscheidet das Fairness-Konto (geringste Last, Audit A-05). Household-scoped, RLS
``household_isolation`` (USING+WITH CHECK), gemeinsamer ``set_updated_and_version``-Trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0029_auto_accept_rules"
down_revision = "0028_marketplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auto_accept_rules (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid NOT NULL,
            template_id uuid,
            max_price integer NOT NULL CHECK (max_price > 0),
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_auto_accept_rules_household_id ON auto_accept_rules (household_id);"
    )
    op.execute("CREATE INDEX ix_auto_accept_rules_member_id ON auto_accept_rules (member_id);")
    op.execute(
        "CREATE TRIGGER trg_auto_accept_rules_updated BEFORE UPDATE ON auto_accept_rules "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE auto_accept_rules ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auto_accept_rules FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON auto_accept_rules "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON auto_accept_rules TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auto_accept_rules CASCADE;")
