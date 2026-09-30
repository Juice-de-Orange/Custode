"""events maint — cross-household dispatcher access for custode_maint

Revision ID: 0004_events_maint
Revises: 0003_events
Create Date: 2026-06-15

The durable outbox dispatcher runs as ``custode_maint`` and must read/update events
across ALL households — it is the delivery worker, not a tenant. A permissive RLS
policy scoped ``TO custode_maint`` grants that, **additively** to ``household_isolation``
(``custode_app`` still sees only its active household). Created inside a role-existence
guard so test databases that only provision ``custode_app`` still migrate cleanly.
"""

from __future__ import annotations

from alembic import op

revision = "0004_events_maint"
down_revision = "0003_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON events_outbox TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                EXECUTE 'CREATE POLICY maint_all ON events_dlq TO custode_maint '
                        'USING (true) WITH CHECK (true)';
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON events_outbox, events_dlq, processed_events TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS maint_all ON events_outbox;")
    op.execute("DROP POLICY IF EXISTS maint_all ON events_dlq;")
