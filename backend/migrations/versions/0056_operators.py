"""operators — Auth-Identitäten der Betreiber-Konsole (eigener Stack, kein Haushalt) (ADR-0015)

Revision ID: 0056_operators
Revises: 0055_ops_views
Create Date: 2026-06-29

Phase 8, P8-S7b (Ops-Console-Auth-Kern): Betreiber-Identitäten — **getrennt** von ``users``,
**kein** ``household_id``, **keine** RLS (Haushalts-Isolation ist hier sinnlos). Passwort +
**Pflicht-TOTP** (ADR-0015: Passkey+TOTP; Passkey folgt). Sicherheit: die App-Rolle ``custode_app``
darf die Operator-Credentials **nie** lesen — die ``ALTER DEFAULT PRIVILEGES``-Grants aus
``init.sql`` werden hier explizit **entzogen**; nur ``ops_readonly`` (Login-Lesen) und
``ops_actions`` (Verwaltung) erhalten Zugriff. Alle Grants ``pg_roles``-guarded (Test-Provision).
"""

from __future__ import annotations

from alembic import op

revision = "0056_operators"
down_revision = "0055_ops_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE operators (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            email varchar(320) NOT NULL UNIQUE,
            password_hash varchar(255) NOT NULL,
            totp_secret varchar(64),
            totp_enabled boolean NOT NULL DEFAULT false,
            is_active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    # Defence in depth: the regular app role must never see operator credentials. Revoke the blanket
    # grant init.sql's ALTER DEFAULT PRIVILEGES would have handed custode_app on this new table.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                REVOKE ALL ON operators FROM custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON operators TO ops_readonly;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
                GRANT SELECT, INSERT, UPDATE ON operators TO ops_actions;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS operators CASCADE;")
