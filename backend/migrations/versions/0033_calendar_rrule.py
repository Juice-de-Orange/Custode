"""calendar — calendar_events.rrule (wiederkehrende Events) (KONZEPT §5.11)

Revision ID: 0033_calendar_rrule
Revises: 0032_calendar
Create Date: 2026-06-24

Phase 5, P5-S2: ``calendar_events`` bekommt ``rrule`` (RFC-5545 Recurrence-Rule, z. B.
``FREQ=WEEKLY;BYDAY=MO``) — NULL für Einzeltermine. Additiv: bestehende Events bleiben Einzel.
Die Occurrences werden beim Lesen gefenstert expandiert (calendar/expand.py, ADR-0041); die
gespeicherten starts_at/ends_at sind die erste Occurrence + Dauer.
"""

from __future__ import annotations

from alembic import op

revision = "0033_calendar_rrule"
down_revision = "0032_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN rrule text;")


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_events DROP COLUMN rrule;")
