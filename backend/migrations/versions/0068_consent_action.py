"""accounts consents — ``action`` (grant/revoke), damit Widerruf ausdrückbar ist (KONZEPT §11)

Revision ID: 0068_consent_action
Revises: 0067_caldav_writeback
Create Date: 2026-07-26

Phase 9, 9-S5: Der Ledger aus 0013 kann bisher nur *erteilte* Einwilligungen abbilden — es gibt
keine Zustandsspalte und (bewusst) kein UPDATE/DELETE-Grant. Für Art.-9-Gesundheitsdaten verlangt
KONZEPT §11 aber einen **widerrufbaren** Consent pro Datentyp. Ein Widerruf als eigener ``type``
(``wearable_sleep_revoked``) wäre String-Semantik durch die Hintertür; stattdessen genau eine
Spalte ``action``.

Append-only bleibt unangetastet: ein Widerruf ist eine **neue Zeile**, nichts wird je geändert.
``granted_by`` heißt damit fachlich „Akteur" (wer erteilt bzw. widerrufen hat).

Reiner Expand-Schritt: nullable-mit-Default, Bestandszeilen werden zu ``grant`` — kein
Contract-Schritt nötig, kein Backfill. Der Index bedient den Fold „letzte Zeile je Typ gewinnt".
"""

from __future__ import annotations

from alembic import op

revision = "0068_consent_action"
down_revision = "0067_caldav_writeback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE consents ADD COLUMN action varchar(10) NOT NULL DEFAULT 'grant';")
    op.execute(
        "ALTER TABLE consents ADD CONSTRAINT ck_consents_action "
        "CHECK (action IN ('grant', 'revoke'));"
    )
    # Fold-Index: DISTINCT ON (type) ... ORDER BY type, created_at DESC — der wirksame Stand
    # je Datentyp ist ein Hot-Path (jeder Ingest-Lauf in 9-S6 prüft ihn pro Mitglied).
    op.execute(
        "CREATE INDEX ix_consents_subject_type "
        "ON consents (subject_user_id, type, created_at DESC);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_consents_subject_type;")
    op.execute("ALTER TABLE consents DROP CONSTRAINT IF EXISTS ck_consents_action;")
    op.execute("ALTER TABLE consents DROP COLUMN IF EXISTS action;")
