"""baseline — shared update trigger, RLS policy template, tenancy_probe

Revision ID: 0001_baseline
Revises:
Create Date: 2026-06-14

Establishes the tenant-isolation machinery (KONZEPT §10, ARCHITECTURE §9):
a shared updated_at/version trigger and a ``tenancy_probe`` table with
``FORCE ROW LEVEL SECURITY`` + household policy. This is the template for every
fact table and makes the RLS negative test (User A ↛ Household B → 0 rows) green
from Phase 0.
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Shared trigger: bump updated_at + version on every UPDATE (feeds ETag/sync).
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_and_version()
        RETURNS trigger AS $$
        BEGIN
            NEW.updated_at := now();
            NEW.version := OLD.version + 1;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    # Probe table — validates the full RLS machinery and is the column template
    # for tenant-scoped tables (KONZEPT §10). uuidv7() is native in Postgres 18.
    op.execute(
        """
        CREATE TABLE tenancy_probe (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            label text NOT NULL DEFAULT '',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_tenancy_probe_household_id ON tenancy_probe (household_id);")
    op.execute(
        """
        CREATE TRIGGER trg_tenancy_probe_updated
        BEFORE UPDATE ON tenancy_probe
        FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();
        """
    )
    # Tenant isolation. FORCE so even a non-superuser table owner is subject.
    op.execute("ALTER TABLE tenancy_probe ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE tenancy_probe FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY household_isolation ON tenancy_probe
        USING (household_id = current_setting('app.household_id', true)::uuid)
        WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);
        """
    )
    # Grant DML to the app role when it exists (dev/prod via infra/postgres/init.sql).
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON tenancy_probe TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenancy_probe;")
    op.execute("DROP FUNCTION IF EXISTS set_updated_and_version();")
