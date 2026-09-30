"""auth sessions — rotating refresh sessions with reuse detection (+ RLS)

Revision ID: 0005_auth_sessions
Revises: 0004_events_maint
Create Date: 2026-06-17

``auth_sessions`` (KONZEPT §8.5): one row per refresh token in a rotation family.
RLS visible to the owning user (``user_id = app.user_id``) for the device list,
logout, and the self-scoped login insert; ``custode_maint`` does the cross-user
refresh lookup (by ``refresh_hash``, before the acting user is known). Refresh
tokens are stored as a SHA-256 hash, never in clear. FK to ``users`` cascades.
"""

from __future__ import annotations

from alembic import op

revision = "0005_auth_sessions"
down_revision = "0004_events_maint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_sessions (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            family_id uuid NOT NULL,
            refresh_hash varchar(64) NOT NULL UNIQUE,
            device_label varchar(120) NOT NULL DEFAULT '',
            user_agent text,
            ip varchar(64),
            issued_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            last_used_at timestamptz NOT NULL DEFAULT now(),
            rotated_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions (user_id);")
    op.execute("CREATE INDEX ix_auth_sessions_family_id ON auth_sessions (family_id);")

    # Tenant/user isolation. FORCE so even a non-superuser owner is subject.
    op.execute("ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auth_sessions FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY user_isolation ON auth_sessions
        USING (user_id = current_setting('app.user_id', true)::uuid)
        WITH CHECK (user_id = current_setting('app.user_id', true)::uuid);
        """
    )

    # custode_maint: cross-user refresh lookup at login/refresh (role-guarded so
    # test DBs that only provision custode_app still migrate).
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON auth_sessions TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions TO custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON auth_sessions TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_sessions CASCADE;")
