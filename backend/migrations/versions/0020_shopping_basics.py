"""shopping_basics — kuratierte Vorlagen-Liste (household-scoped, +RLS), dritte Sync-Entity

Revision ID: 0020_shopping_basics
Revises: 0019_shopping
Create Date: 2026-06-20

Basics = wiederkehrende Posten, die der Haushalt pflegt (Vorlage für 1-Tap-Add). Dritte
Sync-Entity des Moduls — Schreibpfad = **Sync-Batch** (kein PATCH+If-Match). household-scoped
+ RLS (USING + WITH CHECK); Keyset-Index ``(household_id, updated_at, id)`` für den Delta-Pull.
"""

from __future__ import annotations

from alembic import op

revision = "0020_shopping_basics"
down_revision = "0019_shopping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE shopping_basics (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            label varchar(200) NOT NULL,
            category varchar(100),
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_shopping_basics_household_id ON shopping_basics (household_id);")
    op.execute(
        "CREATE INDEX ix_shopping_basics_sync ON shopping_basics (household_id, updated_at, id);"
    )
    op.execute(
        "CREATE TRIGGER trg_shopping_basics_updated BEFORE UPDATE ON shopping_basics "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE shopping_basics ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE shopping_basics FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON shopping_basics "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON shopping_basics TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shopping_basics CASCADE;")
