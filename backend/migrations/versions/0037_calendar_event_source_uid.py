"""calendar — calendar_events.source_uid (ICS-Import-Dedup) (KONZEPT §5.11)

Revision ID: 0037_calendar_event_source_uid
Revises: 0036_calendar_event_exdates
Create Date: 2026-06-24

Phase 5, P5-S6: ``calendar_events`` bekommt ``source_uid`` (die UID aus einem importierten VEVENT).
Damit ist ein erneuter Import derselben .ics idempotent (gleiche UID im Haushalt → übersprungen).
Additiv, nullable; Index pro Haushalt für den Dedup-Lookup. Selbst angelegte Events bleiben NULL.
"""

from __future__ import annotations

from alembic import op

revision = "0037_calendar_event_source_uid"
down_revision = "0036_calendar_event_exdates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN source_uid text;")
    op.execute(
        "CREATE INDEX ix_calendar_events_household_source_uid "
        "ON calendar_events (household_id, source_uid) WHERE source_uid IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_calendar_events_household_source_uid;")
    op.execute("ALTER TABLE calendar_events DROP COLUMN source_uid;")
