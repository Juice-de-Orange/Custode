"""calendar — calendar_events.overrides (Einzel-Occurrence verschieben) (KONZEPT §5.11)

Revision ID: 0040_calendar_event_overrides
Revises: 0039_calendar_event_tzid
Create Date: 2026-06-24

Phase 5, P5-S10: ``calendar_events.overrides`` (jsonb) bildet verschobene Einzeltermine ab —
Schlüssel = Original-Startinstant (ISO-UTC), Wert = ``{"starts_at": iso, "ends_at": iso}`` der neuen
Zeit (RFC-5545 RECURRENCE-ID-Gedanke, kompakt in der Master-Zeile statt als eigene Override-Zeile).
Beim Expandieren ersetzt der Override die generierte Occurrence. Additiv: Default leeres Objekt.
"""

from __future__ import annotations

from alembic import op

revision = "0040_calendar_event_overrides"
down_revision = "0039_calendar_event_tzid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events ADD COLUMN overrides jsonb NOT NULL DEFAULT '{}'::jsonb;"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_events DROP COLUMN overrides;")
