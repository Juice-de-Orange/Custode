"""calendar — calendar_events.tzid (DST-korrekte Serien-Expansion) (KONZEPT §5.11)

Revision ID: 0039_calendar_event_tzid
Revises: 0038_weather_locations
Create Date: 2026-06-24

Phase 5, P5-S9: ``calendar_events`` bekommt ``tzid`` (IANA-Zeitzone, z. B. ``Europe/Vienna``). Eine
wiederkehrende Serie wird in **ihrer** Zone verankert, damit z. B. „wöchentlich 09:00 Wien" über die
Sommer-/Winterzeit-Umstellung hinweg um 09:00 Ortszeit bleibt (nur der UTC-Offset wandert). Additiv:
bestehende Events bekommen ``UTC`` (verhalten sich exakt wie bisher).
"""

from __future__ import annotations

from alembic import op

revision = "0039_calendar_event_tzid"
down_revision = "0038_weather_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN tzid varchar(64) NOT NULL DEFAULT 'UTC';")


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_events DROP COLUMN tzid;")
