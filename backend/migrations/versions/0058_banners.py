"""ops_banners — globale Betreiber-Banner (ops-verwaltet, app-lesbar) (ADR-0015)

Revision ID: 0058_banners
Revises: 0057_audit_log
Create Date: 2026-06-29

Phase 8, P8-S8b: globale Hinweis-Banner (Wartung etc.), die der Betreiber setzt und die App allen
Nutzern anzeigt. **Kein** ``household_id`` (global). Verwaltung **nur** über ``ops_actions``
(auditiert, S8b); ``ops_readonly`` liest sie in der Konsole; ``custode_app`` darf sie **nur lesen**
(aktive Banner anzeigen), nie schreiben (REVOKE des init.sql-Grants, dann gezieltes SELECT).
"""

from __future__ import annotations

from alembic import op

revision = "0058_banners"
down_revision = "0057_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE ops_banners (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            message text NOT NULL,
            level varchar(10) NOT NULL DEFAULT 'info',
            is_active boolean NOT NULL DEFAULT true,
            starts_at timestamptz,
            ends_at timestamptz,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    # The app's hot read is "active banners now"; index the active flag.
    op.execute("CREATE INDEX ix_ops_banners_active ON ops_banners (is_active) WHERE is_active;")
    op.execute(
        """
        DO $$
        BEGIN
            -- App role: read-only (display active banners), never write.
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                REVOKE ALL ON ops_banners FROM custode_app;
                GRANT SELECT ON ops_banners TO custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
                GRANT SELECT, INSERT, UPDATE ON ops_banners TO ops_actions;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON ops_banners TO ops_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ops_banners CASCADE;")
