"""guide_attachments — Datei-Anhänge an Anleitungen (household-scoped, +RLS) (KONZEPT §5)

Revision ID: 0052_guide_attachments
Revises: 0051_vault
Create Date: 2026-06-24

Phase 7, P7-S22: Anhänge zu ``guides`` (Anleitungen). Wie bei Rezept-Fotos (ADR-0033) liegen die
**Bytes im Blob-Storage**, in der DB nur Metadaten + ``storage_key`` (server-generiert, kein
User-Input). Household-scoped, RLS ``household_isolation`` (USING + WITH CHECK) + FORCE, gemeinsamer
Versions-Trigger. ``guide_id`` ist ein nacktes UUID (Modul-intern, Kaskade beim Löschen der
Anleitung erfolgt im Service inkl. Blob-Entfernung — Soft-Delete, daher kein DB-FK-CASCADE).
"""

from __future__ import annotations

from alembic import op

revision = "0052_guide_attachments"
down_revision = "0051_vault"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE guide_attachments (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            guide_id uuid NOT NULL,
            filename varchar(255) NOT NULL,
            content_type varchar(100) NOT NULL,
            byte_size bigint NOT NULL,
            storage_key text NOT NULL,
            uploaded_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_guide_attachments_household_id ON guide_attachments (household_id);"
    )
    # The hot lookup is "all attachments of this guide".
    op.execute(
        "CREATE INDEX ix_guide_attachments_guide ON guide_attachments (guide_id) "
        "WHERE deleted_at IS NULL;"
    )
    op.execute("ALTER TABLE guide_attachments ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE guide_attachments FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON guide_attachments "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON guide_attachments TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_guide_attachments_updated BEFORE UPDATE ON guide_attachments "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS guide_attachments CASCADE;")
