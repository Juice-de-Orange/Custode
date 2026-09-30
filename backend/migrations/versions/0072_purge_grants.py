"""Loeschkaskade — ``users.purged_at`` + die maint-Rechte, die der Purge braucht (11-S1d)

Zwei Dinge, und das zweite ist das, was aus BUGLOG 2026-07-31 gelernt wurde.

**1. ``users.purged_at``.** ``deleted_at`` heisst „zur Loeschung vorgemerkt" (11-S1c setzt es
sofort, die Karenz laeuft ab da). Es kann nicht zugleich „endgueltig ausgeraeumt" heissen — der
Job braucht sonst keinen Anhaltspunkt, welche Konten er schon bearbeitet hat, und ein zweiter Lauf
sieht dieselbe Zeile wieder als faellig. Additiv und nullable (expand/contract).

**2. Die Rechte.** Der Purge laeuft als ``custode_maint`` ueber 14 Tabellen. Eine Bestandsaufnahme
gegen eine frisch migrierte Datenbank ergab: **vier** davon erlauben ihm DELETE, und **vier** haben
ueberhaupt keine ``maint``-Policy — nicht einmal SELECT (``captures``, ``auto_accept_rules``,
``vault_key_envelopes``, ``letter_reads``). ``users`` hat kein UPDATE, die Anonymisierung waere also
ebenfalls gescheitert.

Postgres prueft Tabellenrechte beim **Planen**, nicht beim Treffer. Ein Purge ohne diese Migration
waere jede Nacht mit ``permission denied`` gestorben, unabhaengig davon, ob ueberhaupt ein Konto
faellig war — genau der Ausfall, der den Retention-Reaper monatelang getragen hat. Der Unterschied
diesmal: die Luecke wurde **vor** dem Job gefunden, weil die Liste gegen die Datenbank geprueft
wurde statt geglaubt.

Wie 0071 ergaenzt diese Migration je Tabelle **genau das, was fehlt**, damit der Downgrade nicht
die Arbeit frueherer Migrationen mit zurueckdreht.

Revision ID: 0072_purge_grants
Revises: 0071_retention_grants
"""

from __future__ import annotations

from alembic import op

revision = "0072_purge_grants"
down_revision = "0071_retention_grants"
branch_labels = None
depends_on = None

# Gemessen gegen eine frisch migrierte PG 18 (2026-08-01). ``policy`` sagt, ob die Tabelle die
# ``maint_all``-Policy noch braucht; ``privs`` nennt genau die fehlenden Rechte.
_MISSING: dict[str, tuple[bool, str]] = {
    # Policy fehlt komplett — der Job saehe dort nicht einmal eine Zeile.
    "captures": (True, "SELECT, DELETE"),
    "auto_accept_rules": (True, "SELECT, DELETE"),
    "vault_key_envelopes": (True, "SELECT, DELETE"),
    "letter_reads": (True, "SELECT, DELETE"),
    # Policy vorhanden, DELETE fehlt.
    "auth_login_events": (False, "DELETE"),
    "memberships": (False, "DELETE"),
    "calendar_feeds": (False, "DELETE"),
    "wearable_connections": (False, "DELETE"),
    "feedback": (False, "DELETE"),
    # Die Anonymisierung der users-Zeile braucht UPDATE (Policy seit 0006 vorhanden).
    "users": (False, "UPDATE"),
}


def upgrade() -> None:
    for table, (needs_policy, privs) in _MISSING.items():
        if needs_policy:
            op.execute(
                f"""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint')
                       AND NOT EXISTS (
                           SELECT 1 FROM pg_policy p
                           JOIN pg_class c ON c.oid = p.polrelid
                           WHERE c.relname = '{table}' AND p.polname = 'maint_all'
                       ) THEN
                        EXECUTE 'CREATE POLICY maint_all ON {table} TO custode_maint '
                                'USING (true) WITH CHECK (true)';
                    END IF;
                END $$;
                """  # noqa: S608 - Tabellennamen sind codedefiniert, nie Nutzereingabe
            )
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                    GRANT {privs} ON {table} TO custode_maint;
                END IF;
            END $$;
            """  # noqa: S608 - dito
        )

    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS purged_at timestamptz;")
    # Der Job sucht faellige Konten ueber (deleted_at, purged_at IS NULL). Ohne den Index waere das
    # bei wachsendem Bestand jede Nacht ein Seq Scan ueber alle Nutzer.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_purge_due ON users (deleted_at) "
        "WHERE deleted_at IS NOT NULL AND purged_at IS NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_purge_due;")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS purged_at;")
    for table, (needs_policy, privs) in _MISSING.items():
        op.execute(
            f"""
            DO $$
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'custode_maint') THEN
                    REVOKE {privs} ON {table} FROM custode_maint;
                END IF;
            END $$;
            """  # noqa: S608 - dito
        )
        if needs_policy:
            op.execute(f"DROP POLICY IF EXISTS maint_all ON {table};")
