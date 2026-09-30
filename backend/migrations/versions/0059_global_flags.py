"""global_flags — operator-gesetzte globale Feature-Flag-Overrides (ADR-0015)

Revision ID: 0059_global_flags
Revises: 0058_banners
Create Date: 2026-06-29

Phase 8, P8-S8c: persistente, **operator-gesetzte** globale Feature-Flags. Bisher war die globale
Flag-Ebene nur Env-Config (`settings.feature_flags`); jetzt kann der Betreiber sie zur Laufzeit
überschreiben. Die App liest die Overrides bei der Flag-Auflösung (`accounts.me`), die Konsole setzt
sie **auditiert** über ``ops_actions``. ``custode_app`` darf **nur lesen** (Flag-Auflösung);
Schreiben ist ops-only (REVOKE des init.sql-Grants, dann gezieltes SELECT).
"""

from __future__ import annotations

from alembic import op

revision = "0059_global_flags"
down_revision = "0058_banners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE global_flags (
            key varchar(40) PRIMARY KEY,
            enabled boolean NOT NULL,
            updated_by uuid,
            updated_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                REVOKE ALL ON global_flags FROM custode_app;
                GRANT SELECT ON global_flags TO custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
                GRANT SELECT, INSERT, UPDATE ON global_flags TO ops_actions;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON global_flags TO ops_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS global_flags CASCADE;")
