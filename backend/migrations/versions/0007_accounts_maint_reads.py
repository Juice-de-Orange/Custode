"""accounts maint (join/list) — cross-household *reads* for custode_maint

Revision ID: 0007_accounts_maint_reads
Revises: 0006_accounts_maint
Create Date: 2026-06-17

Accepting an invite, listing a user's households, and verifying a membership before a
household switch are cross-household *reads* keyed by the authenticated user (or a
server-validated invite code) — they happen before/around the household scope, so the
app role's ``household_id``-scoped policies cannot serve them. Extend the maintenance
role to these tables, mirroring 0006 for ``users``. Read-only: the matching writes
(membership insert, invite-use bump) still run as ``custode_app`` scoped to the
server-derived target household, so ``custode_maint`` keeps SELECT only. Role-guarded
so test DBs without ``custode_maint`` still migrate.
"""

from __future__ import annotations

from alembic import op

revision = "0007_accounts_maint_reads"
down_revision = "0006_accounts_maint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON households TO custode_maint USING (true)';
                EXECUTE 'CREATE POLICY maint_all ON memberships TO custode_maint USING (true)';
                EXECUTE 'CREATE POLICY maint_all ON invites TO custode_maint USING (true)';
                GRANT SELECT ON households, memberships, invites TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS maint_all ON households;")
    op.execute("DROP POLICY IF EXISTS maint_all ON memberships;")
    op.execute("DROP POLICY IF EXISTS maint_all ON invites;")
