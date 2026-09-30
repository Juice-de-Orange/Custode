"""object_links — Typisierte Verknüpfungen zwischen Objekten (household-scoped, +RLS) §5.12

Revision ID: 0049_object_links
Revises: 0048_comments
Create Date: 2026-06-24

Phase 7, P7-S8: generische, richtungsunabhängige Verknüpfungen zwischen beliebigen Objekten
(Rezept<->Anleitung, Aufgabe<->Anleitung, Notiz<->Anleitung): ``object_links`` mit zwei
Endpunkten (``src_type``/``src_id`` + ``dst_type``/``dst_id`` als String-Diskriminator + nacktes
UUID, **kein** modulübergreifender FK) + ``relation``. Endpunkte werden serverseitig kanonisch
geordnet (kleinerer ``(type, id)`` zuerst); ein Partial-Unique-Index verhindert symmetrische
Duplikate. Household-scoped, RLS ``household_isolation`` (USING + WITH CHECK) + FORCE,
gemeinsamer Versions-Trigger. ACL / Anhänge / Picker folgen in späteren Slices.
"""

from __future__ import annotations

from alembic import op

revision = "0049_object_links"
down_revision = "0048_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE object_links (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            src_type varchar(40) NOT NULL,
            src_id uuid NOT NULL,
            dst_type varchar(40) NOT NULL,
            dst_id uuid NOT NULL,
            relation varchar(40) NOT NULL,
            created_by uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_object_links_household_id ON object_links (household_id);")
    # Hot lookup "all links touching this object" — index both endpoints.
    op.execute(
        "CREATE INDEX ix_object_links_src ON object_links (src_type, src_id) "
        "WHERE deleted_at IS NULL;"
    )
    op.execute(
        "CREATE INDEX ix_object_links_dst ON object_links (dst_type, dst_id) "
        "WHERE deleted_at IS NULL;"
    )
    # Canonical endpoints + relation are unique per household (no symmetric duplicates).
    op.execute(
        "CREATE UNIQUE INDEX ux_object_links_pair ON object_links "
        "(household_id, src_type, src_id, dst_type, dst_id, relation) WHERE deleted_at IS NULL;"
    )
    op.execute("ALTER TABLE object_links ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE object_links FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON object_links "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON object_links TO custode_app;
            END IF;
        END $$;
        """
    )
    op.execute(
        "CREATE TRIGGER trg_object_links_updated BEFORE UPDATE ON object_links "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS object_links CASCADE;")
