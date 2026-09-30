"""calendar — external_calendar_subscriptions (CalDAV-Abos, household-scoped +RLS) (KONZEPT §10)

Revision ID: 0065_caldav_subscriptions
Revises: 0064_operator_passkeys
Create Date: 2026-07-22

Phase 9, 9-S2: Datenmodell für externe CalDAV-Abos (Nextcloud/iCloud; Google folgt als
OAuth-Slice). Pro Mitglied und Kollektions-URL ein Abo; ``creds_enc`` trägt ausschließlich
SecretBox-Werte (``v1:<fernet>``, ADR-0077) über ``{username, password}`` — NULL = anonymer
Zugriff. ``enabled`` pausiert ohne Löschen; ``last_sync_at`` bleibt in 9-S2 NULL und wird vom
Pull-Sync-Cron (9-S3) gefüllt. Household-RLS ``household_isolation`` (USING + WITH CHECK) +
FORCE, gemeinsamer Versions-Trigger. Die ``maint_all``-SELECT-Policy für ``custode_maint``
wird hier mit angelegt (Muster 0034): der 15-min-Cron aus 9-S3 zählt Abos haushaltsübergreifend
auf und liest/schreibt die Fachdaten dann pro Haushalt unter ``scoped_session``.
"""

from __future__ import annotations

from alembic import op

revision = "0065_caldav_subscriptions"
down_revision = "0064_operator_passkeys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE external_calendar_subscriptions (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid NOT NULL,
            label varchar(100) NOT NULL,
            caldav_url varchar(2000) NOT NULL,
            creds_enc text,
            enabled boolean NOT NULL DEFAULT true,
            last_sync_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz
        );
        """
    )
    op.execute(
        "CREATE INDEX ix_external_calendar_subscriptions_household_id "
        "ON external_calendar_subscriptions (household_id);"
    )
    op.execute(
        "CREATE INDEX ix_external_calendar_subscriptions_member_id "
        "ON external_calendar_subscriptions (member_id);"
    )
    # One live subscription per member+URL; partial so a soft-deleted row allows re-subscribing.
    op.execute(
        "CREATE UNIQUE INDEX uq_external_calendar_subscriptions_member_url "
        "ON external_calendar_subscriptions (member_id, caldav_url) WHERE deleted_at IS NULL;"
    )
    op.execute(
        "CREATE TRIGGER trg_external_calendar_subscriptions_updated "
        "BEFORE UPDATE ON external_calendar_subscriptions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
    )
    op.execute("ALTER TABLE external_calendar_subscriptions ENABLE ROW LEVEL SECURITY;")
    op.execute("ALTER TABLE external_calendar_subscriptions FORCE ROW LEVEL SECURITY;")
    op.execute(
        "CREATE POLICY household_isolation ON external_calendar_subscriptions "
        "USING (household_id = current_setting('app.household_id', true)::uuid) "
        "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid);"
    )
    op.execute(
        """
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON external_calendar_subscriptions TO custode_app;
            END IF;
            -- Cross-household enumeration for the 9-S3 pull-sync cron (read-only).
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                EXECUTE 'CREATE POLICY maint_all ON external_calendar_subscriptions '
                        'TO custode_maint USING (true) WITH CHECK (true)';
                GRANT SELECT ON external_calendar_subscriptions TO custode_maint;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS external_calendar_subscriptions CASCADE;")
