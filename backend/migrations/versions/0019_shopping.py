"""shopping — Einkaufsliste (household-scoped, +RLS) + sync_client_ops (Sync-Batch-Idempotenz)

Revision ID: 0019_shopping
Revises: 0018_ingredient_nutrition
Create Date: 2026-06-20

Erste offlinefähige Entität (Phase 3). Schreibpfad = **Sync-Batch** (ARCHITECTURE §10), nicht
PATCH+If-Match. ``shopping_items.checked`` ist ein eigenes Feld (Konfliktarmut: Abhaken kollidiert
nie mit Umbenennen — LWW pro Feldgruppe). ``sync_client_ops`` ist das Idempotenz-Log
(``(household_id, client_op_id)`` unique). Keyset-Index ``(household_id, updated_at, id)`` für den
Delta-Pull (Phase 3 S2). source-Enum ``manual|basic|mealplan`` (mealplan-Pfad ab Phase 6).
"""

from __future__ import annotations

from alembic import op

revision = "0019_shopping"
down_revision = "0018_ingredient_nutrition"
branch_labels = None
depends_on = None

_SCOPED = ("shopping_lists", "shopping_items", "sync_client_ops")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE shopping_lists (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            name varchar(100) NOT NULL,
            category_order varchar[] NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE shopping_items (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            list_id uuid NOT NULL REFERENCES shopping_lists(id),
            label varchar(200) NOT NULL,
            qty varchar(40),
            unit varchar(40),
            category varchar(100),
            checked boolean NOT NULL DEFAULT false,
            checked_by uuid,
            source varchar(10) NOT NULL DEFAULT 'manual',
            notes text,
            reserved_by uuid,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE sync_client_ops (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            client_op_id uuid NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_sync_client_ops UNIQUE (household_id, client_op_id)
        );
        """
    )

    op.execute("CREATE INDEX ix_shopping_lists_household_id ON shopping_lists (household_id);")
    op.execute("CREATE INDEX ix_shopping_items_household_id ON shopping_items (household_id);")
    op.execute("CREATE INDEX ix_shopping_items_list_id ON shopping_items (list_id);")
    # Keyset cursor index for the delta-pull (Phase 3 S2): (household_id, updated_at, id).
    op.execute(
        "CREATE INDEX ix_shopping_lists_sync ON shopping_lists (household_id, updated_at, id);"
    )
    op.execute(
        "CREATE INDEX ix_shopping_items_sync ON shopping_items (household_id, updated_at, id);"
    )
    op.execute("CREATE INDEX ix_sync_client_ops_created ON sync_client_ops (created_at);")

    for table in ("shopping_lists", "shopping_items"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
        )

    for table in _SCOPED:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        op.execute(
            f"CREATE POLICY household_isolation ON {table} "
            f"USING (household_id = current_setting('app.household_id', true)::uuid) "
            f"WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
        )

    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                ON shopping_lists, shopping_items, sync_client_ops TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS shopping_items CASCADE;")
    op.execute("DROP TABLE IF EXISTS sync_client_ops CASCADE;")
    op.execute("DROP TABLE IF EXISTS shopping_lists CASCADE;")
