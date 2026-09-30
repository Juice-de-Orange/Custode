"""operator passkeys — WebAuthn credentials for the Betreiber-Konsole (ADR-0072-Erweiterung)

Revision ID: 0064_operator_passkeys
Revises: 0063_digest_task_reads
Create Date: 2026-07-07

Operator passkeys mirror ``auth_passkeys`` (0010) but belong to an **operator** (separate identity
space, NO household, NO RLS — isolation is by ``operator_id`` + DB-role grants, exactly like the
``operators`` table, migration 0056). ``custode_app`` is REVOKEd (defence-in-depth vs. an ALTER
DEFAULT PRIVILEGES auto-grant); ``ops_readonly`` may SELECT (list + the pre-auth login lookup),
``ops_actions`` may SELECT/INSERT/UPDATE/DELETE (enroll, sign_count bump, delete). FK cascades on
operator removal.
"""

from __future__ import annotations

from alembic import op

revision = "0064_operator_passkeys"
down_revision = "0063_digest_task_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE operator_passkeys (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            operator_id uuid NOT NULL REFERENCES operators(id) ON DELETE CASCADE,
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
    op.execute("CREATE INDEX ix_operator_passkeys_operator_id ON operator_passkeys (operator_id);")
    # No RLS: operators have no household/RLS (the app.* GUCs are never set on ops sessions).
    # Isolation = operator_id + the grants below.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                REVOKE ALL ON operator_passkeys FROM custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON operator_passkeys TO ops_readonly;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON operator_passkeys TO ops_actions;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operator_passkeys CASCADE;")
