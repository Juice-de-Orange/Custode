# Modul `messaging`

**Status:** in Arbeit · **Phase:** 7 · **KONZEPT:** §5.12 (Messaging / „Briefe")

## Zweck & Verantwortung
Ruhige, asynchrone **Briefe** an den Haushalt (KONZEPT §5.12, Ebene 3 — kein Chat). P7-S4 ist das
**Fundament**: Betreff + Markdown-Body von einem Mitglied, **Rundbrief** (leeres `to_ids`) oder an
adressierte Mitglieder, mit **Gelesen-Status**. System-Notifications (Ebene 1) und Objekt-Kommentare
(Ebene 2) sind eigene spätere Slices. Importiert **nur** `kernel/*`; kein Modul liest seine Tabellen.

## Datenobjekte (Migration 0046, ADR-0062)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `letters` | id; `from_id`; `to_ids uuid[]` (leer = Rundbrief); `subject` (≤200); `body_md`; `version` = ETag (Trigger) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |
| `letter_reads` | id; `letter_id`→`letters` (CASCADE); `user_id`; `read_at`; **append-only**, unique `(letter_id, user_id)` | `household_id = app.household_id` (USING + WITH CHECK) + FORCE |

RLS-Negativtest (`test_messaging_rls.py`: A↛B→0, WITH CHECK) für `letters` **und** `letter_reads`.

## Gelesen-Status (ADR-0062)
Gelesen wird als **eigene Tabelle** `letter_reads` geführt (statt `read_map_json`): eine append-only
Zeile je (Brief, Leser), `INSERT … ON CONFLICT DO NOTHING` (concurrency-sicher, idempotent). `GET /{id}`
markiert nur dann gelesen, wenn der Leser **Empfänger** ist (Rundbrief **oder** in `to_ids`) und **nicht**
der Absender. `read_count` = distinkte Leser; `read_by_me` = Read-Zeile für den Betrachter existiert.

## Schreibpfad
- **Online-first**, kein Sync-Batch. Senden = `POST`; `version` (Trigger) ist der ETag (für spätere
  Edits/If-Match). Soft-Delete-Spalte vorhanden (Löschen = Folge-Slice).

## Schnittstellen (HTTP, `/v1/letters`)
- `GET` (member) → `list[LetterSummary]` (empfangen + gesendet, neueste zuerst, `read_by_me`/`read_count`).
- `GET /unread-count` (member) → `UnreadCount {unread}` (an mich adressiert, ungelesen, nicht von mir).
- `POST` (member/admin, CSRF, 201) → `LetterResponse` (+ETag). `from_id` aus dem Principal; `to_ids`
  leer = Rundbrief.
- `GET /{id}` (member) → `LetterResponse`; markiert gelesen (falls Empfänger). 404 fremd/gelöscht.
- `POST /{id}/to-task` (member/admin, CSRF, 201) → `LetterToTaskResult {task_id, title}`
  („Kümmerst du dich?", P7-S5, ADR-0063): legt aus dem **Betreff** eine persönliche Aufgabe an (über
  `tasks.api`, points 0, an den Auslöser); **non-destruktiv** (der Brief bleibt). 404 wenn weg.
- **Cross-Modul:** liest **nur** `tasks.api` („Kümmerst du dich?", einseitig); `messaging.api` ist leer;
  sonstige Reaktion über `letter.*`-Events.

## Events
- **publiziert:** `letter.created`, `letter.read` — transactional outbox; SSE-Invalidation via
  `handlers.py` (`letter.* → entity "letters"`).
- **abonniert:** — (die Notification-Fan-out hört später auf `letter.*`).

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `GET /letters`, `GET /letters/{id}` | ✗ (401) | ✗ (403) | ✓ | RLS: nur eigene (404) |
| `POST /letters` | ✗ | ✗ (403) | ✓ | **RLS** |

## Tests
- `test_messaging_rls.py` — RLS-Negativ + WITH CHECK für `letters` + `letter_reads` (Testcontainers).
- `test_messaging_http.py` — Rundbrief-Lesefluss (ungelesen → öffnen markiert gelesen, idempotent,
  read_count 1, unread 0); eigener Brief sichtbar aber nie ungelesen + keine Read-Zeile; adressierter
  Brief trifft nur den Empfänger; fremder Brief → 404; „Kümmerst du dich?"→Task (Aufgabe points 0/
  Caller, Brief bleibt), Konvertieren-404.

## „Kümmerst du dich?" → Aufgabe (P7-S5, ADR-0063)
`POST /v1/letters/{id}/to-task` legt aus dem Brief-**Betreff** eine persönliche Aufgabe an (über
`tasks.api.create_personal_task`, points 0, an den **Auslöser** = Empfänger, der annimmt). Non-destruktiv
(der Brief bleibt). 404 wenn weg. Modulgrenze: `messaging` liest nur `tasks.api` (einseitig).

## Web-Einbettungen
- **Kommentar-Thread (P7-S21):** das Brief-Detail bettet die generische `CommentThread`-Komponente
  (`objectType="letter"`) ein — ruhige Diskussion an einem Brief ohne neuen Brief. Briefe sind nicht
  löschbar → kein comments-Reaper nötig (keine Waisen).

## Offene Punkte (spätere Slices)
- **Anhang/Bild** (Blob-Storage), **@-Mentions** (Ebene 2), **System-Notifications + Fan-out**
  (Ebene 1: Web Push/E-Mail-Digest auf `letter.*`/Event-Basis), Brief löschen/archivieren,
  persistenter Brief↔Task-`object_link`.
