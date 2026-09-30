"""wearables — wearable_connections + wearable_daily, **member-scoped** RLS (KONZEPT §5.15/§10)

Revision ID: 0069_wearables
Revises: 0068_consent_action
Create Date: 2026-07-26

Phase 9, 9-S5: Gefäß für Oura-OAuth-Verbindungen und die daraus gelesenen Tageswerte. Der Cron
füllt ``wearable_daily`` erst in 9-S6; die Tabelle entsteht hier, weil (a) der RLS-Negativtest
seine eigentliche Aussage nur an den *Gesundheitsdaten* trifft und (b) der Lösch-Pfad sie
referenziert. Präzedenz: 0065 legte ``last_sync_at`` an, das bis 9-S3 NULL blieb.

**Die Abweichung vom Hausmuster — hier steht die Entscheidung des Slices (ADR-0081):**
Alle bisherigen Fachtabellen tragen ``household_isolation`` allein auf ``household_id``;
owner-only läuft app-seitig (``ExternalCalendarSubscription``: jeder Read filtert ``member_id``,
0065 + calendar/service.py). Für Art.-9-Gesundheitsdaten ist das zu wenig:

* KONZEPT §5.15 verlangt wörtlich „getrennte Tabellen mit **engem** Zugriff" — haushaltsweit ist
  genau so eng wie eine Einkaufsliste.
* N-2 (KONZEPT §9, „Wearable-Daten ↛ andere Mitglieder — auch nicht für Admins") steht in
  derselben Verbindlichkeitsklasse wie „keine negativen Salden". Die wird im Repo DB-erzwungen,
  nicht per Kommentar. Bei CalDAV kostet eine vergessene WHERE-Klausel einen sichtbaren
  Fremdtermin; hier wäre sie eine meldepflichtige Verletzung.

Deshalb ``member_isolation``: ``household_id`` UND ``member_id`` im Prädikat. Kein neuer
Mechanismus — ``app.user_id`` setzt ``kernel/tenancy/session.py`` auf jeder scoped session, und
user-scoped Policies sind seit 0005 erprobt (``auth_sessions``); neu ist nur, dass eine
**Fachtabelle** sie nutzt. Die Rolle steht bewusst NICHT im Prädikat: es gibt DB-seitig keine
Admin-Ausnahme.

Kosten, die wir bewusst kaufen: der 9-S6-Cron muss pro Verbindung ``scoped_session(household_id,
user_id=member_id)`` öffnen (genau das tut der CalDAV-Sync bereits). Für die Aufzählung bekommt
``custode_maint`` eine ``maint_all``-Policy **SELECT-only** (Muster 0065); ``DELETE`` für den
90-Tage-Reaper folgt in der 9-S6-Migration (Least Privilege pro Slice). ``ops_readonly`` bekommt
**keinen** Grant — die Betreiber-Grenze kennt keine Gesundheitsdaten.

``CHECK (deleted_at IS NULL)``: Art. 9 verlangt Löschen, das wirklich löscht. Der Mixin bringt
``deleted_at`` mit; ein nie genutztes Tombstone-Feld wäre ein Footgun. Der CHECK macht die Regel
DB-erzwungen und hält beide Tabellen zugleich aus ``_RETENTION_TABLES`` (app/worker.py) heraus.
"""

from __future__ import annotations

from alembic import op

revision = "0069_wearables"
down_revision = "0068_consent_action"
branch_labels = None
depends_on = None

_TABLES = ("wearable_connections", "wearable_daily")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE wearable_connections (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid NOT NULL,
            provider varchar(20) NOT NULL
                CHECK (provider IN ('oura', 'garmin', 'healthconnect')),
            -- EIN SecretBox-Wert ('v1:<fernet>', ADR-0077) ueber
            -- {access_token, refresh_token, token_type, scopes}. NULL = noch kein Tausch.
            tokens_enc text,
            -- BEWUSST Klartext: der 9-S6-Cron filtert "laeuft bald ab" per SQL, ohne jede
            -- Zeile entschluesseln zu muessen. Ein Ablaufzeitpunkt ist kein Geheimnis.
            token_expires_at timestamptz,
            scopes text[] NOT NULL DEFAULT '{}',
            status varchar(20) NOT NULL DEFAULT 'active'
                CHECK (status IN ('active', 'needs_reauth')),
            -- Kategorie-Slug, nie Token/URL/Antwortinhalt (Muster last_sync_error, 0065).
            last_error varchar(40),
            last_sync_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            CONSTRAINT ck_wearable_connections_hard_delete CHECK (deleted_at IS NULL)
        );
        """
    )
    op.execute(
        """
        CREATE TABLE wearable_daily (
            id uuid PRIMARY KEY DEFAULT uuidv7(),
            household_id uuid NOT NULL,
            member_id uuid NOT NULL,
            provider varchar(20) NOT NULL
                CHECK (provider IN ('oura', 'garmin', 'healthconnect')),
            day date NOT NULL,
            sleep_score smallint CHECK (sleep_score BETWEEN 0 AND 100),
            sleep_minutes integer CHECK (sleep_minutes >= 0),
            readiness smallint CHECK (readiness BETWEEN 0 AND 100),
            steps integer CHECK (steps >= 0),
            active_kcal integer CHECK (active_kcal >= 0),
            rhr smallint CHECK (rhr BETWEEN 20 AND 250),
            fetched_at timestamptz NOT NULL DEFAULT now(),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            version bigint NOT NULL DEFAULT 1,
            deleted_at timestamptz,
            CONSTRAINT ck_wearable_daily_hard_delete CHECK (deleted_at IS NULL)
        );
        """
    )

    op.execute(
        "CREATE INDEX ix_wearable_connections_household_id ON wearable_connections (household_id);"
    )
    op.execute(
        "CREATE INDEX ix_wearable_connections_member_id ON wearable_connections (member_id);"
    )
    # Eindeutigkeit MUSS household_id enthalten, sonst passt sie nicht zur Policy: ein Mensch
    # kann in mehreren Haushalten Mitglied sein, und Verbindung wie Consent gehoeren jeweils zu
    # (Haushalt, Mitglied). Ohne household_id im Index sieht die Duplikatspruefung des Service
    # (RLS-gefiltert auf den aktiven Haushalt) nichts, waehrend das INSERT am globalen Index
    # scheitert — aus einem sauberen 409 wuerde eine rohe Unique-Violation.
    op.execute(
        "CREATE UNIQUE INDEX uq_wearable_connections_member_provider "
        "ON wearable_connections (household_id, member_id, provider);"
    )
    op.execute("CREATE INDEX ix_wearable_daily_household_id ON wearable_daily (household_id);")
    # Deckt den 9-S6-Ingest (member+day) und die spaetere Retention (day) ab. Der Schluessel
    # bleibt partitionstauglich, falls wearable_daily je monatlich partitioniert wird (ARCH §9).
    op.execute(
        "CREATE UNIQUE INDEX uq_wearable_daily_member_provider_day "
        "ON wearable_daily (household_id, member_id, provider, day);"
    )

    for table in _TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_and_version();"
        )
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        # Der Kern des Slices: Mandant UND Eigentuemer. Ein Mitbewohner (auch ein Admin)
        # sieht DB-seitig 0 Zeilen — nicht erst, weil der Service filtert.
        op.execute(
            f"CREATE POLICY member_isolation ON {table} "
            "USING (household_id = current_setting('app.household_id', true)::uuid "
            "   AND member_id = current_setting('app.user_id', true)::uuid) "
            "WITH CHECK (household_id = current_setting('app.household_id', true)::uuid "
            "   AND member_id = current_setting('app.user_id', true)::uuid);"
        )
        # S608 unterdrueckt: ``table`` stammt aus der Modul-Konstante _TABLES (zwei Literale),
        # nie aus Eingaben. Die Schleife ist hier eine Sicherheitseigenschaft, keine
        # Bequemlichkeit — sie garantiert, dass BEIDE Tabellen byte-identische Policies
        # bekommen; zwei ausgeschriebene Bloecke koennten auseinanderdriften, und genau das
        # waere der Bug.
        op.execute(
            f"""
            DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_app') THEN
                    GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO custode_app;
                END IF;
                -- Haushaltsuebergreifende Aufzaehlung fuer den 9-S6-Cron: READ-ONLY.
                -- Geschrieben wird ausschliesslich unter scoped_session des Mitglieds;
                -- DELETE fuer den Retention-Job kommt mit dessen eigener Migration.
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                    EXECUTE 'CREATE POLICY maint_all ON {table} '
                            'TO custode_maint USING (true) WITH CHECK (true)';
                    GRANT SELECT ON {table} TO custode_maint;
                END IF;
            END $$;
            """  # noqa: S608
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wearable_daily CASCADE;")
    op.execute("DROP TABLE IF EXISTS wearable_connections CASCADE;")
