"""accounts maint — cross-user user lookup for custode_maint (login bootstrap)

Revision ID: 0006_accounts_maint
Revises: 0005_auth_sessions
Create Date: 2026-06-17

Login/refresh run as ``custode_maint`` and must find a user by e-mail *before* the
user is scoped. ``users`` has RLS (``user_visibility``) and was granted only to
``custode_app`` (migration 0002). Add a permissive maint policy + SELECT grant so
the bootstrap lookup works. Role-guarded so test DBs without ``custode_maint``
still migrate. SELECT only — the maint bootstrap reads users, never writes them.
"""

from __future__ import annotations

from alembic import op

revision = "0006_accounts_maint"
down_revision = "0005_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON users TO custode_maint USING (true)';
                GRANT SELECT ON users TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS maint_all ON users;")
