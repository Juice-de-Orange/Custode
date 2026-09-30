# Modul `notes`

**Status:** in Arbeit · **Phase:** 7 · **KONZEPT:** §5 (Notizen)

## Zweck & Verantwortung
Haushalts-**Notizen** (Markdown). P7-S1 ist das **manuelle Fundament**: Titel + Markdown-Body, optional
ans Dashboard **gepinnt**, mit `author_id`. Versions-Historie (5 Versionen), „Konvertieren-zu"
(Notiz↔Task/Rezept/…), die Dashboard-Pin-**Sicht**, Kommentare/@-Mentions und `object_links` bauen in
späteren Slices darauf auf. Importiert **nur** `kernel/*`; kein Modul liest seine Tabellen.

## Datenobjekte (Migrationen 0044/0045, ADR-0059/0060)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `notes` | id; `author_id`; `title` (≤200); `body_md` (Text); `pinned` (bool); `version` = ETag (Trigger) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |
| `note_versions` (P7-S2) | id; `note_id`→`notes` (CASCADE); `version_no` (= abgelöste Notiz-`version`, unique pro Notiz); `title`; `body_md`; `edited_by`; **append-only**, max 5 je Notiz | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |

Partial-Index `ix_notes_household_pinned` auf `pinned WHERE NOT deleted` (für die spätere Pin-Sicht).
RLS-Negativtest (`test_notes_rls.py`: A↛B→0, WITH CHECK) für `notes` **und** `note_versions`.

## Versions-Historie (P7-S2, ADR-0060)
Jede **Inhaltsänderung** (Titel/Body) von `update_note` archiviert den **vorherigen** Stand als
`note_versions`-Snapshot (`version_no` = die abgelöste Notiz-`version`) und kappt auf die **letzten 5**.
Ein reiner **Pin-Toggle** erzeugt **keine** Version. `GET /v1/notes/{id}/versions` (neueste zuerst, max 5).
`POST /v1/notes/{id}/restore?version_no=` archiviert zuerst den aktuellen Stand (Restore ist rückgängig
machbar) und setzt dann Titel/Body aus dem Snapshot; 404 bei unbekannter Version.

## Schreibpfad
- **PATCH + If-Match** (ADR-0029): `version` (Mixin-Spalte, Trigger-bumped) ist der ETag; 412 bei
  stale, 428 bei fehlend. **Kein Sync-Batch** (online-first; Offline-Dexie = spätere Option).
- **Soft-Delete** (Historie bleibt für die spätere Versions-/Wiederherstellungs-Funktion).

## Schnittstellen (HTTP, `/v1/notes`)
- `GET ?pinned=` (Member) → `list[NoteSummary]` (gepinnt zuerst, dann neueste Änderung; `?pinned=true`
  nur die gepinnten).
- `POST` (member/admin, CSRF, 201) → `NoteResponse` (+ETag). `author_id` aus dem Principal.
- `GET {id}` (Member, +ETag) → `NoteResponse`.
- `PATCH {id}` (member/admin, If-Match, CSRF) → `NoteResponse` (+neuer ETag). 412 bei stale.
- `DELETE {id}` (member/admin, CSRF, 204) → Soft-Delete.
- `GET /trash` (member) → `list[TrashedNote {id, title, deleted_at}]` (soft-gelöscht, neueste zuerst,
  P8-S4). Vor `GET {id}` deklariert, damit `trash` nicht als UUID geparst wird.
- `POST {id}/untrash` (member/admin, CSRF) → `NoteResponse`; **Papierkorb**-Wiederherstellung (setzt
  `deleted_at` zurück), 404 wenn die Notiz nicht im Papierkorb ist. Bleibt bis P8-S3-Reaper (30 Tage).
- `GET {id}/versions` (member) → `list[NoteVersionResponse]` (neueste zuerst, max 5).
- `POST {id}/restore?version_no=` (member/admin, CSRF) → `NoteResponse`; **Versions**-Restore (≠
  Papierkorb); 404 bei unbekannter Version.
- `POST {id}/to-task` (member/admin, CSRF, 201) → `ToTaskResult {task_id, title}` („Konvertieren-zu",
  P7-S3, ADR-0061): legt aus dem Notiz-**Titel** eine persönliche Aufgabe an (über `tasks.api`, points 0,
  an den Auslöser); **non-destruktiv** (die Notiz bleibt). 404 wenn die Notiz weg ist.
- **Cross-Modul:** liest **nur** `tasks.api` (Konvertieren-zu, einseitig); `notes.api` ist leer; sonstige
  Reaktion läuft über `note.*`-Events.

## Events
- **publiziert:** `note.created`, `note.updated`, `note.deleted` — transactional outbox
  (`kernel/events/emit.py`); SSE-Invalidation via `handlers.py` (`note.* → entity "notes"`).
- **abonniert:** —

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `GET /notes`, `GET /notes/{id}`, `GET /notes/trash` | ✗ (401) | ✗ (403) | ✓ | RLS: nur eigene (404) |
| `POST/PATCH/DELETE /notes`, `POST /notes/{id}/untrash` | ✗ | ✗ (403) | ✓ | **RLS** (404 fremd/weg) |

## Tests
- `test_notes_rls.py` — RLS-Negativ + WITH CHECK für `notes` **und** `note_versions` (Testcontainers).
- `test_notes_http.py` — CRUD; Pin sortiert zuerst (+`?pinned=`); If-Match bumpt Version, stale → 412;
  Löschen → 404 danach; fremde Notiz → 404; Versions-Historie (max 5, neueste zuerst), Pin-Toggle
  erzeugt keine Version, Restore round-trip (+ alter Stand bleibt in der Historie), Restore-404;
  Konvertieren-zu-Task (Aufgabe entsteht points 0/Caller, Notiz bleibt), Konvertieren-404;
  Papierkorb-Roundtrip (löschen → `/trash` → `untrash` → wieder aktiv & aus Papierkorb, untrash-404).

## Offene Punkte (spätere Slices)
- **Konvertieren-zu** weitere Zieltypen (Notiz→Rezept) + persistenter `object_link`,
  **Dashboard-Pin-Sicht**, **Kommentare/@-Mentions**, `object_links` (Notiz↔Anleitung/Rezept),
  Markdown-Rendering, optionale Offline-Bearbeitung.
