"""recipes — last_cooked_at + cooked_count (Mealplanner-Historie) (KONZEPT §5.2/§5.4)

Revision ID: 0043_recipe_cooked_history
Revises: 0042_mealplanner
Create Date: 2026-06-24

Phase 6, P6-S3: ``recipes`` bekommt eine „zuletzt gekocht"-Historie, gespeist vom Mealplanner
(`mealplan.cooked`): ``last_cooked_at`` (timestamptz) + ``cooked_count`` (wie oft gekocht). Additiv;
Fundament fuer die spaetere Wiederholungs-Sperre der Automatik.
"""

from __future__ import annotations

from alembic import op

revision = "0043_recipe_cooked_history"
down_revision = "0042_mealplanner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE recipes ADD COLUMN last_cooked_at timestamptz;")
    op.execute("ALTER TABLE recipes ADD COLUMN cooked_count integer NOT NULL DEFAULT 0;")


def downgrade() -> None:
    op.execute("ALTER TABLE recipes DROP COLUMN cooked_count;")
    op.execute("ALTER TABLE recipes DROP COLUMN last_cooked_at;")
