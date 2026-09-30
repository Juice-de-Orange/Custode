"""auth recovery codes — one-time TOTP backup codes (+ RLS)

Revision ID: 0009_recovery_codes
Revises: 0008_users_totp
Create Date: 2026-06-17

One-time recovery codes for TOTP (login fallback when the authenticator is lost). Stored
as a SHA-256 hash, never in clear; single-use via ``used_at``. RLS visible to the owning
user (``user_id = app.user_id``) for generate/regenerate/count; ``custode_maint`` consumes
one at login (cross-user lookup by hash, before scope). FK to ``users`` cascades. Mirrors
``auth_sessions`` (0005).
"""

from __future__ import annotations

from alembic import op

revision = "0009_recovery_codes"
down_revision = "0008_users_totp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_recovery_codes (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            code_hash varchar(64) NOT NULL UNIQUE,
            used_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_auth_recovery_codes_user_id ON auth_recovery_codes (user_id);")

    op.execute("ALTER TABLE auth_recovery_codes ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auth_recovery_codes FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY user_isolation ON auth_recovery_codes
        USING (user_id = current_setting('app.user_id', true)::uuid)
        WITH CHECK (user_id = current_setting('app.user_id', true)::uuid);
        """
    )

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON auth_recovery_codes TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT, INSERT, UPDATE, DELETE ON auth_recovery_codes TO custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON auth_recovery_codes TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_recovery_codes CASCADE;")
