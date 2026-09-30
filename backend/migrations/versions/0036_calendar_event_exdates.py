"""calendar — calendar_events.exdates (Einzel-Occurrence-Ausnahmen / EXDATE) (KONZEPT §5.11)

Revision ID: 0036_calendar_event_exdates
Revises: 0035_calendar_event_kind
Create Date: 2026-06-24

Phase 5, P5-S5: ``calendar_events`` bekommt ``exdates`` (timestamptz[]) — die abgesagten
Einzeltermine einer Serie (RFC-5545 EXDATE). Beim Expandieren werden Occurrences mit passendem
``starts_at`` herausgefiltert; im ICS-Feed werden sie als EXDATE mitgegeben. Additiv: bestehende
Events haben eine leere Ausnahmeliste.
"""

from __future__ import annotations

from alembic import op

revision = "0036_calendar_event_exdates"
down_revision = "0035_calendar_event_kind"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE calendar_events "
        "ADD COLUMN exdates timestamptz[] NOT NULL DEFAULT '{}'::timestamptz[];"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_events DROP COLUMN exdates;")
