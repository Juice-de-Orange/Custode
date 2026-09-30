"""audit_log — append-only Sicherheits-/Betreiber-Audit (ADR-0015/ADR-0073)

Revision ID: 0057_audit_log
Revises: 0056_operators
Create Date: 2026-06-29

Phase 8, P8-S8a: append-only Audit-Log für Betreiber-Aktionen (Banner/Flags/… in S8) und
Sicherheitsereignisse. **DB-erzwungen append-only**: kein Rollen-Grant für UPDATE/DELETE (nur
INSERT/SELECT für die ops-Rollen), Korrektur = neue Zeile. Globaler Log (optionales ``household_id``
für haushaltsbezogene Aktionen, Transparenz-Sicht folgt). Die App-Rolle ``custode_app`` ist
**ausgesperrt** (REVOKE des ``ALTER DEFAULT PRIVILEGES``-Grants aus ``init.sql``) — der Log ist
ops-only. **Kein PII** im ``detail_json`` (Aufrufer-Pflicht). Alle Grants ``pg_roles``-guarded.
"""

from __future__ import annotations

from alembic import op

revision = "0057_audit_log"
down_revision = "0056_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_log (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            occurred_at timestamptz NOT NULL DEFAULT now(),
            actor_type varchar(20) NOT NULL,
            actor_id uuid,
            action varchar(80) NOT NULL,
            target_type varchar(40),
            target_id uuid,
            household_id uuid,
            detail_json jsonb NOT NULL DEFAULT '{}'::jsonb,
            request_id varchar(64)
        );
        """
    )
    op.execute("CREATE INDEX ix_audit_log_occurred ON audit_log (occurred_at DESC);")
    op.execute(
        "CREATE INDEX ix_audit_log_household ON audit_log (household_id) "
        "WHERE household_id IS NOT NULL;"
    )
    # Append-only at the grant level: ops_actions may INSERT + read, ops_readonly may read; NOBODY
    # is granted UPDATE/DELETE (corrections are new rows). The app role is locked out entirely (the
    # security log is ops-only) — revoke the blanket grant init.sql would hand it.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                REVOKE ALL ON audit_log FROM custode_app;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_actions') THEN
                GRANT INSERT, SELECT ON audit_log TO ops_actions;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON audit_log TO ops_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
