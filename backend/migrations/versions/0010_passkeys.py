"""auth passkeys — WebAuthn credentials (+ RLS)

Revision ID: 0010_passkeys
Revises: 0009_recovery_codes
Create Date: 2026-06-17

WebAuthn passkeys (KONZEPT §8): one row per authenticator, keyed by ``credential_id``
(base64url). RLS visible to the owning user for register/list/delete; ``custode_maint`` does
the cross-user lookup at passwordless login (by ``credential_id``, before the user is known).
FK to ``users`` cascades. Mirrors ``auth_sessions`` (0005).
"""

from __future__ import annotations

from alembic import op

revision = "0010_passkeys"
down_revision = "0009_recovery_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_passkeys (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            credential_id varchar(512) NOT NULL UNIQUE,
            public_key text NOT NULL,
            sign_count bigint NOT NULL DEFAULT 0,
            name varchar(120) NOT NULL DEFAULT '',
            transports varchar(120),
            created_at timestamptz NOT NULL DEFAULT now(),
            last_used_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_auth_passkeys_user_id ON auth_passkeys (user_id);")

    op.execute("ALTER TABLE auth_passkeys ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auth_passkeys FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY user_isolation ON auth_passkeys
        USING (user_id = current_setting('app.user_id', true)::uuid)
        WITH CHECK (user_id = current_setting('app.user_id', true)::uuid);
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON auth_passkeys TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT, INSERT, UPDATE, DELETE ON auth_passkeys TO custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON auth_passkeys TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_passkeys CASCADE;")
