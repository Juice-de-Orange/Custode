"""auth login events — login audit log (country code only, no PII) (+ RLS)

Revision ID: 0011_login_events
Revises: 0010_passkeys
Create Date: 2026-06-18

``auth_login_events`` (ARCHITECTURE §12, ADR-0025): one row per login attempt. **User-scoped**
audit, NOT tenant-scoped — login is pre-household, so RLS keys on ``user_id = app.user_id``
(like ``auth_sessions``), not ``household_id``. Stores only ``country_code`` (from an edge
header); never the IP, e-mail, or any token. Written by ``custode_maint`` (the login
bootstrap); a user can read their own attempts. ``user_id`` is NULL for an unknown e-mail.
"""

from __future__ import annotations

from alembic import op

revision = "0011_login_events"
down_revision = "0010_passkeys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_login_events (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            user_id uuid,
            success boolean NOT NULL,
            country_code varchar(2),
            created_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_auth_login_events_user_id_created "
        "ON auth_login_events (user_id, created_at);"
    )

    # User isolation: a user reads only their own attempts (NULL-user rows stay maint-only).
    # FORCE so even a non-superuser owner is subject. No WITH CHECK — the app role never
    # writes (maint does), so there is no insert/update path to constrain.
    op.execute("ALTER TABLE auth_login_events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE auth_login_events FORCE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY user_isolation ON auth_login_events
        USING (user_id = current_setting('app.user_id', true)::uuid);
        """
    )

    # custode_maint writes the audit at login (cross-user, before the user is scoped);
    # custode_app may read (a user's own attempts). Role-guarded so test DBs that only
    # provision custode_app still migrate.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON auth_login_events TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT, INSERT ON auth_login_events TO custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT ON auth_login_events TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_login_events CASCADE;")
