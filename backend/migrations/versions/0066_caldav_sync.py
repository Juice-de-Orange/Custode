"""calendar — Pull-Sync-Spiegel: subscription_id an calendar_events + last_sync_error (P9-S3)

Revision ID: 0066_caldav_sync
Revises: 0065_caldav_subscriptions
Create Date: 2026-07-23

Phase 9, 9-S3 (ADR-0079): Der 15-min-Cron spiegelt externe CalDAV-Termine als
``calendar_events``-Zeilen (``layer='personal'``, Owner = Abo-Inhaber). ``subscription_id``
markiert die Herkunft (NULL = lokal/ICS-Import, Bestandsverhalten) und trägt ``ON DELETE
CASCADE`` als Backstop, wenn der Retention-Reaper ein soft-gelöschtes Abo hart entsorgt.
Der partielle Unique-Index (Abo, VEVENT-UID) ist der Idempotenz-Backstop gegen parallel
laufende Sync-Ticks; partial, damit ein remote gelöschtes und wieder aufgetauchtes Event
neu angelegt werden kann. ``last_sync_error`` hält den letzten Fehlergrund als Kategorie-Slug
(nie URL/Inhalt); NULL = letzter Lauf erfolgreich. Keine neuen Grants/Policies nötig:
``custode_app`` hat DML auf beiden Tabellen, RLS greift unter ``scoped_session``.
"""

from __future__ import annotations

from alembic import op

revision = "0066_caldav_sync"
down_revision = "0065_caldav_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events ADD COLUMN subscription_id uuid "
        "REFERENCES external_calendar_subscriptions(id) ON DELETE CASCADE;"
    )
    # The sync's diff query reads only mirror rows of one subscription.
    op.execute(
        "CREATE INDEX ix_calendar_events_subscription_id "
        "ON calendar_events (subscription_id) WHERE subscription_id IS NOT NULL;"
    )
    # Idempotency backstop: one live mirror row per (subscription, VEVENT-UID).
    op.execute(
        "CREATE UNIQUE INDEX uq_calendar_events_subscription_uid "
        "ON calendar_events (subscription_id, source_uid) "
        "WHERE subscription_id IS NOT NULL AND deleted_at IS NULL;"
    )
    op.execute(
        "ALTER TABLE external_calendar_subscriptions ADD COLUMN last_sync_error varchar(200);"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE external_calendar_subscriptions DROP COLUMN IF EXISTS last_sync_error;")
    op.execute("DROP INDEX IF EXISTS uq_calendar_events_subscription_uid;")
    op.execute("DROP INDEX IF EXISTS ix_calendar_events_subscription_id;")
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS subscription_id;")
