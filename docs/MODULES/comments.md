# Modul `comments`

**Status:** in Arbeit · **Phase:** 7 · **KONZEPT:** §5.12 (Kommentare an Objekten)

## Zweck & Verantwortung
**Generische Kommentare/Threads** an beliebigen Objekten (Rezept, Task, Event, Liste, Anleitung).
P7-S7 ist das **Fundament**: ein Markdown-Kommentar mit Autor, referenziert über
`(object_type, object_id)` — **kein** modulübergreifender FK. @-Mentions + Notification-Fan-out folgen
in späteren Slices. Importiert **nur** `kernel/*`; kein Modul liest seine Tabelle.

## Datenobjekte (Migration 0048, ADR-0065)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `comments` | id; `object_type` (≤40, String-Diskriminator); `object_id` (nacktes UUID, kein FK); `author_id`; `body_md`; `version` (Trigger) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |

Partial-Index `ix_comments_object` auf `(object_type, object_id) WHERE NOT deleted` (Hot-Lookup
„Thread eines Objekts"). RLS-Negativtest (`test_comments_rls.py`: A↛B→0, WITH CHECK).

## Generische Referenz (ADR-0065)
`object_type` ist ein String (`"guide"`/`"recipe"`/`"task"`/…), `object_id` ein nacktes UUID. So kennt
`comments` **keines** der kommentierten Module (und umgekehrt); ein neues kommentierbares Objekt braucht
**null** Backend-Änderung. Keine referenzielle Integrität (verwaiste Kommentare bei Objekt-Löschung
möglich — Aufräumen via `*.deleted`-Events = später).

## Schreibpfad
- **Online-first**, kein Sync-Batch. Threads werden **älteste zuerst** gelistet. **Löschen/Editieren
  nur der Autor** (403 sonst), Soft-Delete. **Editieren = PATCH + If-Match** (P7-S18, ADR-0029):
  `version` (Trigger-bumped) ist der ETag; 412 bei zwischenzeitlicher Änderung. Der Thread trägt
  `version` je Eintrag → Inline-Edit **ohne** Einzel-GET.

## Schnittstellen (HTTP, `/v1/comments`)
- `GET ?object_type=&object_id=` (member) → `list[CommentResponse]` (Thread, älteste zuerst; je
  Eintrag `version` + `updated_at`).
- `POST` (member/admin, CSRF, 201, +ETag) → `CommentResponse`. `author_id` aus dem Principal.
- `PATCH /{id}` (member/admin, CSRF, If-Match) → `body_md` ändern, nur eigener (403 sonst, 404 wenn
  weg, 412 stale); +ETag.
- `DELETE /{id}` (member/admin, CSRF, 204) → Soft-Delete, nur eigener (403 sonst, 404 wenn weg).
- **Cross-Modul:** **keins** — `comments.api` ist leer; Reaktion über `comment.*`-Events.

## Events
- **publiziert:** `comment.created`, `comment.updated`, `comment.deleted` → SSE-Entity `"comments"`.
- **abonniert (Reaper, P7-S20):** `recipe.deleted` · `note.deleted` · `guide.deleted` →
  `service.purge_for_object` soft-deletet die Kommentare des gelöschten Objekts. Handler am
  Worker-Composition-Root registriert (kein Kernel-Import), Event nur per Name gematcht (kein
  Fremdmodul-Import), idempotent. (`task` bewusst ausgeklammert: `task.deleted` ist ein
  *Template*-Event, Kommentar-`task`-Endpunkte referenzieren *Instanzen* — späterer Slice.)

## Web
Wiederverwendbare `CommentThread`-Komponente (`web/src/comments/thread.tsx`) — eingebettet an
Anleitung (`guide`), Rezept (`recipe`), Notiz (`note`) und **Brief (`letter`, P7-S21)**; an
weiteren Objekttypen nachrüstbar.
**Inline-Editieren** (P7-S18): „Bearbeiten" am eigenen Eintrag öffnet ein Feld; Speichern sendet
`PATCH` mit `If-Match` aus der im Thread getragenen `version`.

## Tests
- `test_comments_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers).
- `test_comments_http.py` — Posten + Thread-Reihenfolge (älteste zuerst); object_id-Scoping;
  Löschen nur durch Autor (403 sonst); fremder Haushalt sieht denselben object_id nicht (RLS);
  **Editieren mit If-Match** (Body geändert + Version steigt), **stale If-Match → 412**, **nur Autor
  editiert → 403**.
- `test_reaper_orphans.py` — Reaper-E2E (P7-S20): Anleitung mit Kommentar + Link löschen → Outbox
  treiben → Kommentar/Link soft-deletet; unbeteiligte Kommentare bleiben.

## Offene Punkte (spätere Slices)
- **@-Mentions** (→ Notifications), Markdown-Rendering, Einbettung an weiteren Objekttypen,
  **Task-Instanz-Reaper** (sobald ein Instanz-Lösch-Event existiert).
