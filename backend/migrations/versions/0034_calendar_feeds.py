"""calendar — calendar_feeds (ICS-Secret-Feed, household-scoped +RLS +maint-Lookup) (KONZEPT §5.11)

Revision ID: 0034_calendar_feeds
Revises: 0033_calendar_rrule
Create Date: 2026-06-24

Phase 5, P5-S3: ``calendar_feeds`` — pro Mitglied ein geheimes ICS-Abo-Token. Die CRUD läuft
household-scoped (RLS ``household_isolation``); der **unauthentifizierte** Feed-Endpoint löst das
Token **haushaltsübergreifend** über eine ``maint_all``-SELECT-Policy für ``custode_maint`` auf
(wie der Auth-Token-Lookup, ADR-0042). Gemeinsamer ``set_updated_and_version``-Trigger.
"""

from __future__ import annotations

from alembic import op

revision = "0034_calendar_feeds"
down_revision = "0033_calendar_rrule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE calendar_feeds (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid NOT NULL,
            token varchar(64) NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute("CREATE UNIQUE INDEX ix_calendar_feeds_token ON calendar_feeds (token);")
    op.execute("CREATE INDEX ix_calendar_feeds_household_id ON calendar_feeds (household_id);")
    op.execute("CREATE INDEX ix_calendar_feeds_member_id ON calendar_feeds (member_id);")
    op.execute(
        "CREATE TRIGGER trg_calendar_feeds_updated BEFORE UPDATE ON calendar_feeds "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE calendar_feeds ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE calendar_feeds FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON calendar_feeds "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON calendar_feeds TO custode_app;
            END IF;
            -- Cross-household token resolution for the unauthenticated ICS endpoint (read-only).
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON calendar_feeds TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT ON calendar_feeds TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calendar_feeds CASCADE;")
