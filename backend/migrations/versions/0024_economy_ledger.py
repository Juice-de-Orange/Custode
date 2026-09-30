"""economy — points_ledger (household-scoped, +RLS) (KONZEPT §5.9, ADR-0035)

Revision ID: 0024_economy_ledger
Revises: 0023_tasks
Create Date: 2026-06-23

Erstes Phase-4-Ökonomie-Modul. Append-only Doppelbuchungs-Ledger: eine Bewegung = eine Zeile
``from_account -> to_account`` mit ``amount > 0`` (CHECK). Konten als Strings (``system``,
``member:<uuid>``, ``escrow:<uuid>``). Salden sind SUMMEN, nie gespeichert. Standard-Mixin-Spalten
(``version``/``updated_at``/``deleted_at`` bleiben ungenutzt — die Zeilen werden nie geändert oder
gelöscht; Korrektur = neue Gegenbuchung). RLS ``household_isolation`` (USING+WITH CHECK);
gemeinsamer ``set_updated_and_version``-Trigger (aus 0001).
"""

from __future__ import annotations

from alembic import op

revision = "0024_economy_ledger"
down_revision = "0023_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE points_ledger (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            from_account varchar(80) NOT NULL,
            to_account varchar(80) NOT NULL,
            amount integer NOT NULL CHECK (amount > 0),
            ref_type varchar(40) NOT NULL,
            ref_id uuid,
            note text,
            created_by uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            CHECK (from_account <> to_account)
        );
        """
    )
    op.execute("CREATE INDEX ix_points_ledger_household_id ON points_ledger (household_id);")
    # Balance queries sum by account within a household; the read path filters on these.
    op.execute("CREATE INDEX ix_points_ledger_from ON points_ledger (household_id, from_account);")
    op.execute("CREATE INDEX ix_points_ledger_to ON points_ledger (household_id, to_account);")

    op.execute(
        "CREATE TRIGGER trg_points_ledger_updated BEFORE UPDATE ON points_ledger "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE points_ledger ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE points_ledger FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON points_ledger "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )

    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON points_ledger TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS points_ledger CASCADE;")
