"""household_metadata — Aggregat-View für die Betreiber-Support-Suche (ADR-0015/0071)

Revision ID: 0060_household_metadata
Revises: 0059_global_flags
Create Date: 2026-06-29

Phase 8, P8-S8d: der Support muss einen Haushalt anhand von ID/Name nachschlagen können — aber **nur
Metadaten** (Org-Ebene: Name, Anlagedatum, Mitglieder-/Admin-Zahl), **nie** Fachinhalte (Rezepte,
Aufgaben, Nachrichten …). Wie die KPI-Views (0055): security-definer, Owner ``custode_maint``
(aggregiert via ``maint_all`` über alle Haushalte); ``ops_readonly`` erhält **SELECT nur auf die
View**.
"""

from __future__ import annotations

from alembic import op

revision = "0060_household_metadata"
down_revision = "0059_global_flags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE VIEW household_metadata AS
        SELECT
            h.id,
            h.name,
            h.created_at,
            count(m.id) FILTER (WHERE m.deleted_at IS NULL) AS member_count,
            count(m.id) FILTER (WHERE m.deleted_at IS NULL AND m.role = 'admin') AS admin_count
        FROM households h
        LEFT JOIN memberships m ON m.household_id = h.id
        WHERE h.deleted_at IS NULL
        GROUP BY h.id, h.name, h.created_at;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                GRANT CREATE ON SCHEMA public TO custode_maint;
                ALTER VIEW household_metadata OWNER TO custode_maint;
                REVOKE CREATE ON SCHEMA public FROM custode_maint;
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ops_readonly') THEN
                GRANT SELECT ON household_metadata TO ops_readonly;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS household_metadata;")
