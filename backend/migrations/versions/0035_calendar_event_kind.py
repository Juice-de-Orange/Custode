"""calendar — calendar_events.kind (Abwesenheit/Gast Event-Flags) (KONZEPT §5.11)

Revision ID: 0035_calendar_event_kind
Revises: 0034_calendar_feeds
Create Date: 2026-06-24

Phase 5, P5-S4: ``calendar_events`` bekommt ``kind`` (normal | absence | guest) — Event-Flags.
``absence`` markiert ein Mitglied als abwesend (Naht für Scheduling/Fairness über ``calendar.api``),
``guest`` flaggt Besuch. Additiv: bestehende Events sind ``normal``.
"""

from __future__ import annotations

from alembic import op

revision = "0035_calendar_event_kind"
down_revision = "0034_calendar_feeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN kind varchar(10) NOT NULL DEFAULT 'normal';")
    op.execute(
        "ALTER TABLE calendar_events ADD CONSTRAINT calendar_events_kind_check "
        "CHECK (kind IN ('normal', 'absence', 'guest'));"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_events DROP CONSTRAINT calendar_events_kind_check;")
    op.execute("ALTER TABLE calendar_events DROP COLUMN kind;")
