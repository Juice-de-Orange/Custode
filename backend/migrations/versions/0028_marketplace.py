"""marketplace — market_listings (household-scoped, +RLS) (KONZEPT §5.10)

Revision ID: 0028_marketplace
Revises: 0027_rooms
Create Date: 2026-06-23

Handelbare Aufgaben (P4-S8a): ``market_listings`` mit Status-Maschine
``open -> accepted -> settled`` / ``open -> withdrawn`` / ``accepted -> reverted``. Der Preis wird
beim Listing in ``escrow:<listing_id>`` (economy-Ledger) reserviert; bei Erledigung an den Käufer,
bei Rückzug/Verfall an den Verkäufer — alles über das append-only Ledger (ADR-0035), keine
gespeicherten Salden. ``task_instance_id`` ist eine reine ID (kein Cross-Modul-FK). RLS
``household_isolation`` (USING+WITH CHECK), gemeinsamer ``set_updated_and_version``-Trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0028_marketplace"
down_revision = "0027_rooms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market_listings (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            task_instance_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            seller_id uuid NOT NULL,
            price integer NOT NULL CHECK (price > 0),
            status varchar(10) NOT NULL DEFAULT 'open'
                CHECK (status IN ('open', 'accepted', 'settled', 'reverted', 'withdrawn')),
            buyer_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_market_listings_household_id ON market_listings (household_id);")
    op.execute(
        "CREATE INDEX ix_market_listings_task_instance_id ON market_listings (task_instance_id);"
    )
    op.execute(
        "CREATE TRIGGER trg_market_listings_updated BEFORE UPDATE ON market_listings "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE market_listings ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE market_listings FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON market_listings "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON market_listings TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS market_listings CASCADE;")
