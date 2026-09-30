"""calendar — Write-back-Anker: ext_href/ext_etag an calendar_events (P9-S4, ADR-0080)

Revision ID: 0067_caldav_writeback
Revises: 0066_caldav_sync
Create Date: 2026-07-23

Phase 9, 9-S4: Der Write-back braucht pro Spiegel-Zeile den server-absoluten Ressourcen-Pfad
(``ext_href`` — Ziel für GET/PUT/DELETE) und den zuletzt bekannten Server-ETag (``ext_etag`` —
If-Match beim DELETE; NULL = nächster Write unconditional). Beide sind nur für Spiegel-Zeilen
(``subscription_id IS NOT NULL``) belegt und werden vom Pull-Sync bei **jedem** Lauf gestempelt —
Alt-Spiegel aus 9-S3 heilen damit binnen eines Ticks (bis dahin: 409 ``external_not_synced``).
Werte sind fremdkontrolliert → ``text`` wie ``source_uid``. Kein Index (Zugriff über die id),
keine neuen Grants/Policies.
"""

from __future__ import annotations

from alembic import op

revision = "0067_caldav_writeback"
down_revision = "0066_caldav_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE calendar_events ADD COLUMN ext_href text;")
    op.execute("ALTER TABLE calendar_events ADD COLUMN ext_etag text;")


def downgrade() -> None:
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS ext_etag;")
    op.execute("ALTER TABLE calendar_events DROP COLUMN IF EXISTS ext_href;")
