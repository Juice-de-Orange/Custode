"""events — outbox, processed_events, dead-letter queue (+ RLS)

Revision ID: 0003_events
Revises: 0002_accounts
Create Date: 2026-06-15

Domain-event delivery machinery (ARCHITECTURE §8.2). ``events_outbox`` and
``events_dlq`` are household-scoped (RLS on ``app.household_id``) — the write path
(``custode_app``) appends in the same transaction as the fact change.
``processed_events`` is an internal ``(handler, event_id)`` idempotency ledger
without tenant data, hence no RLS. The cross-household dispatcher read path
(``custode_maint``) is added together with the dispatcher itself.
"""

from __future__ import annotations

from alembic import op

revision = "0003_events"
down_revision = "0002_accounts"
branch_labels = None
depends_on = None

_SCOPED = ("events_outbox", "events_dlq")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE events_outbox (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            type varchar(100) NOT NULL,
            version integer NOT NULL DEFAULT 1,
            household_id uuid NOT NULL,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            processed_at timestamptz,
            attempts integer NOT NULL DEFAULT 0,
            next_attempt_at timestamptz NOT NULL DEFAULT now(),
            last_error text
        );
        """
    )
    op.execute("CREATE INDEX ix_events_outbox_type ON events_outbox (type);")
    op.execute("CREATE INDEX ix_events_outbox_household_id ON events_outbox (household_id);")
    # Dispatcher poll index: undispatched rows that are due, oldest attempt first.
    op.execute(
        "CREATE INDEX ix_events_outbox_due ON events_outbox (next_attempt_at) "
        "WHERE processed_at IS NULL;"
    )

    op.execute(
        """
        CREATE TABLE processed_events (
            handler varchar(200) NOT NULL,
            event_id uuid NOT NULL,
            processed_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (handler, event_id)
        );
        """
    )

    op.execute(
        """
        CREATE TABLE events_dlq (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            event_id uuid NOT NULL,
            type varchar(100) NOT NULL,
            household_id uuid NOT NULL,
            payload jsonb NOT NULL,
            attempts integer NOT NULL,
            last_error text,
            failed_at timestamptz NOT NULL DEFAULT now()
        );
        """
    )
    op.execute("CREATE INDEX ix_events_dlq_household_id ON events_dlq (household_id);")
    op.execute("CREATE INDEX ix_events_dlq_event_id ON events_dlq (event_id);")

    # Tenant isolation on the household-scoped event tables. FORCE so even a
    # non-superuser owner is subject; the write path is custode_app.
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
                    ON events_outbox, events_dlq, processed_events TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in ("events_dlq", "processed_events", "events_outbox"):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
