# CLAUDE.md — Modul `notes`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Haushalts-Notizen (KONZEPT §5). P7-S1 = manuelles Fundament: Titel + Markdown-Body + Dashboard-Pin.
Versions-Historie / Konvertieren-zu / Pin-Sicht / Kommentare = spätere Slices.

## Grenzen (hart)
- Importiert **nur** `kernel/*` + `tasks.api` („Konvertieren-zu Aufgabe", P7-S3, ADR-0061) — nie
  deren Interna oder ein anderes Modul (import-linter: „notes uses only tasks public api"). Quermodul
  sonst nur über Domain-Events (`note.*`) — `notes.api` ist leer, kein Modul importiert `notes`.
- Jede Fachzeile (`notes`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest (`test_notes_rls.py`).
  `household_id`/`author_id` kommen aus dem Principal/RLS, nie aus einem Cross-Modul-Import.

## RLS (Migrationen 0044/0045, ADR-0059/0060)
- `notes`: `household_id = app.household_id` (USING + WITH CHECK) + FORCE + gemeinsamer Versions-Trigger.
- `note_versions` (P7-S2): household-scoped, RLS USING+WITH CHECK + FORCE, **append-only** (kein Mixin).
- Negativtest je Tabelle: Haushalt A ↛ Haushalt B → 0 Zeilen.

## Versions-Historie (P7-S2)
- Inhaltsänderung (Titel/Body) → Snapshot des **alten** Stands in `note_versions` (`version_no` = die
  abgelöste Notiz-`version`), Kappung auf **5**. **Pin-Toggle erzeugt keine Version.** Restore archiviert
  zuerst den aktuellen Stand (rückgängig machbar). ADR-0060.

## Schreibpfad
- **PATCH + If-Match** (ADR-0029): `version` (Mixin, Trigger-bumped) = ETag; 412 stale, 428 fehlend.
  **Kein Sync-Batch** (online-first). Soft-Delete (Historie bleibt für die spätere Versions-Funktion).

## Schnittstellen (HTTP, `/v1/notes`)
- `GET ?pinned=` (member) · `POST` (member/admin, CSRF, 201) · `GET {id}` (+ETag) ·
  `PATCH {id}` (member/admin, If-Match, CSRF) · `DELETE {id}` (member/admin, CSRF, 204) ·
  `GET /trash` (member; soft-gelöschte Notizen, P8-S4) · `POST {id}/untrash` (member/admin, CSRF;
  Papierkorb-Wiederherstellung, 404 wenn nicht im Papierkorb) ·
  `GET {id}/versions` (member) · `POST {id}/restore?version_no=` (member/admin, CSRF; **Versions**-
  Restore, nicht Papierkorb) · `POST {id}/to-task` (member/admin, CSRF, 201 → `{task_id, title}`).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `note.created`, `note.updated`, `note.deleted` → SSE-Entity `"notes"` (`handlers.py`).
- **abonniert:** —

## No-Gos
- Kein Sync-Batch + If-Match für denselben Typ mischen (online-first → nur If-Match).
- `notes` importiert **kein** anderes Modul; Reaktion nur über `note.*`-Events.
- Hard-Deletes vermeiden (Soft-Delete; Historie bleibt für die Versions-Funktion). Der **einzige**
  sanktionierte Hard-Delete ist der Retention-Reaper (`kernel/retention`, P8-S3): er entfernt
  `notes`-Tombstones erst nach Ablauf des 30-Tage-Fensters (`note_versions` kaskadieren per FK).
