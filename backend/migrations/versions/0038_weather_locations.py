"""weather — weather_locations (household-scoped, +RLS) (KONZEPT §5.14)

Revision ID: 0038_weather_locations
Revises: 0037_calendar_event_source_uid
Create Date: 2026-06-24

Phase 5, P5-S7: ``weather_locations`` — der grobe Haushalts-Standort für die Wetter-Vorhersage
(Open-Meteo). Ein Eintrag pro Haushalt (Upsert). Household-scoped, RLS ``household_isolation``
(USING+WITH CHECK), gemeinsamer ``set_updated_and_version``-Trigger. Wetter ist optional (Graceful
Enhancement): ohne Standort liefert die API leere Vorhersagen (Basis-Pfad).
"""

from __future__ import annotations

from alembic import op

revision = "0038_weather_locations"
down_revision = "0037_calendar_event_source_uid"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE weather_locations (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            lat double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
            lon double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
            label varchar(120),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_weather_locations_household_id ON weather_locations (household_id);"
    )
    op.execute(
        "CREATE TRIGGER trg_weather_locations_updated BEFORE UPDATE ON weather_locations "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE weather_locations ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE weather_locations FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON weather_locations "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON weather_locations TO custode_app;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS weather_locations CASCADE;")
