"""economy — rewards + redemptions (household-scoped, +RLS) (KONZEPT §5.9)

Revision ID: 0025_rewards
Revises: 0024_economy_ledger
Create Date: 2026-06-23

Belohnungskatalog (P4-S3): ``rewards`` (admin-definiert, ``cost > 0`` CHECK, optional
stock/cooldown, ``version`` = ETag für PATCH+If-Match) + ``redemptions`` (Einlösung; Punkte werden
beim Einlösen member->system gebucht; Status ``requested -> fulfilled``, nie hard-deleted). Beide
household-scoped, RLS ``household_isolation`` (USING+WITH CHECK), Standard-Trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0025_rewards"
down_revision = "0024_economy_ledger"
branch_labels = None
depends_on = None

_TABLES = ("rewards", "redemptions")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE rewards (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            description text,
            cost integer NOT NULL CHECK (cost > 0),
            stock integer CHECK (stock IS NULL OR stock >= 0),
            cooldown_hours integer CHECK (cooldown_hours IS NULL OR cooldown_hours >= 0),
            kind varchar(20) NOT NULL DEFAULT 'standard',
            active boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        """
        CREATE TABLE redemptions (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            reward_id uuid NOT NULL REFERENCES rewards(id),
            member_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            cost integer NOT NULL,
            status varchar(10) NOT NULL DEFAULT 'requested'
                CHECK (status IN ('requested', 'fulfilled')),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE INDEX ix_rewards_household_id ON rewards (household_id);")
    op.execute("CREATE INDEX ix_redemptions_household_id ON redemptions (household_id);")
    op.execute("CREATE INDEX ix_redemptions_reward_id ON redemptions (reward_id);")
    op.execute("CREATE INDEX ix_redemptions_member_id ON redemptions (member_id);")

    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
        )
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
                GRANT SELECT, INSERT, UPDATE, DELETE ON rewards, redemptions TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS redemptions CASCADE;")
    op.execute("DROP TABLE IF EXISTS rewards CASCADE;")
