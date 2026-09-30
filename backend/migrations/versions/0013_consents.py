"""accounts consents — append-only consent ledger (+ RLS) (KONZEPT §5.1/§5.11)

Revision ID: 0013_consents
Revises: 0012_users_email_verified
Create Date: 2026-06-19

Household-scoped, **append-only** consent records (parental consent for children, per-type
wearable/vault consent). One row per granted consent; never updated or deleted, so the app role
gets only SELECT + INSERT (no UPDATE/DELETE) and there is no updated_at/version trigger. RLS
isolates by ``app.household_id`` (USING for reads, WITH CHECK so an INSERT can only write the
active household). Written by future flows (S12 children); created here with the flags increment.
"""

from __future__ import annotations

from alembic import op

revision = "0013_consents"
down_revision = "0012_users_email_verified"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE consents (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            subject_user_id uuid NOT NULL,
            type varchar(40) NOT NULL,
            granted_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_consents_household_id ON consents (household_id);")

    op.execute("ALTER TABLE consents ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE consents FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY household_isolation ON consents
        USING (household_id = current_setting('app.household_id', true)::uuid)
        WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT ON consents TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS consents CASCADE;")
