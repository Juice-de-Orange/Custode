"""calendar — calendar_events (household-scoped, +RLS) (KONZEPT §5.11)

Revision ID: 0032_calendar
Revises: 0031_task_activation
Create Date: 2026-06-24

Phase 5, P5-S1: ``calendar_events`` — der persönliche + Haushaltskalender. ``layer`` trennt die
Sichtbarkeit (``household`` für alle, ``personal`` nur für ``owner_id`` — query-seitig, ADR-0040);
``busy`` ist das spätere „belegt"-Signal der Scheduling-Engine. Household-scoped, RLS
``household_isolation`` (USING+WITH CHECK), gemeinsamer ``set_updated_and_version``-Trigger,
CHECKs für ``layer`` und ``ends_at >= starts_at``.
"""

from __future__ import annotations

from alembic import op

revision = "0032_calendar"
down_revision = "0031_task_activation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE calendar_events (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            owner_id uuid NOT NULL,
            title varchar(200) NOT NULL,
            description text,
            location varchar(200),
            starts_at timestamptz NOT NULL,
            ends_at timestamptz NOT NULL,
            all_day boolean NOT NULL DEFAULT false,
            layer varchar(10) NOT NULL DEFAULT 'household'
                CHECK (layer IN ('household', 'personal')),
            busy boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            CONSTRAINT calendar_events_range_check CHECK (ends_at >= starts_at)
        );
        """
    )
    op.execute("CREATE INDEX ix_calendar_events_household_id ON calendar_events (household_id);")
    op.execute("CREATE INDEX ix_calendar_events_owner_id ON calendar_events (owner_id);")
    op.execute("CREATE INDEX ix_calendar_events_starts_at ON calendar_events (starts_at);")
    op.execute(
        "CREATE TRIGGER trg_calendar_events_updated BEFORE UPDATE ON calendar_events "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE calendar_events ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE calendar_events FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON calendar_events "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON calendar_events TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calendar_events CASCADE;")
