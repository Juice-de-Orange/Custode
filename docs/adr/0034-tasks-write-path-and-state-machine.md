# ADR-0034: Haushaltsaufgaben — Schreibpfad PATCH + If-Match & Erledigen-Zustandsmaschine

- **Status:** beschlossen
- **Datum:** 2026-06-23
- **Betrifft:** `modules/tasks`, `kernel/http`, `kernel/events` · **Bezug:** KONZEPT §5.9/§5.10, ARCHITECTURE §10 (Sync), §7 (API), Roadmap Phase 4
- **Bezug ADRs:** ADR-0029 (PATCH+If-Match), ADR-0032 (Sync-Batch)

## Kontext

Phase 4 startet mit den Haushaltsaufgaben (KONZEPT §5.9): Task-Templates erzeugen Task-Instanzen,
deren Erledigung später (Folge-Slice) eine **Punkte-Ledger-Buchung** auslöst. Die Punkte-Ökonomie ist
ein append-only Doppelbuchungs-Ledger mit harten Invarianten (amount > 0, keine negativen Salden) — die
Erledigung **muss daher serverautoritativ** sein (der Server stempelt `done_by`/`done_at`, der Client
darf das nicht fälschen, und eine Erledigung darf nicht doppelt zählen).

ARCHITECTURE §10 stellt zwei Schreibpfade bereit: den **Sync-Batch** (LWW pro Feldgruppe, Idempotenz
via `client_op_id`) ausschließlich für **offlinefähige** Entitäten, und **PATCH + If-Match** (ADR-0029)
für alles andere. Aufgaben sind in S1 **online-first** (Web-Offline für Aufgaben ist nicht im Scope;
Android-Caching erst Phase 10). Sie brauchen optimistische Nebenläufigkeit gegen gleichzeitige Edits
und — entscheidend — eine Erledigung, die **nicht** unter Last-Writer-Wins „verschmilzt".

## Entscheidung

**Aufgaben nutzen PATCH + If-Match** (ADR-0029-Maschinerie, `kernel/http/conditional.py::parse_if_match`),
**nicht** den Sync-Batch. Der ETag ist die `HouseholdScoped.version`-Spalte (Trigger-bumped). Konkret:

1. **Templates:** Standard-CRUD; `PATCH`/`DELETE` tragen `If-Match` (412 stale / 428 fehlend). Löschen
   = Soft-Delete (`deleted_at`), **ohne** Kaskade auf bereits erzeugte Instanzen (Historie bleibt).
2. **Instanzen:** Erstellung manuell (aus Template → Snapshot von `title`/`points`, oder ad-hoc).
   **Keine Hard-Deletes** — der Lebenszyklus ist eine **Zustandsmaschine** `open → done` (S1) bzw.
   `open → expired` (späterer Worker). Die Erledigung ist eine **dedizierte Aktion**
   `POST /v1/tasks/instances/{id}/complete` (kein Feld-PATCH), weil sie ein Domänenübergang ist und
   serverseitige Felder atomar stempelt (`done_by = principal.user_id`, `done_at`). Sie ist **mit
   If-Match** abgesichert (stale → 412) **und** durch einen Statuswächter (Status ≠ `open` → **409**),
   damit ein Doppel-Submit `task.completed` nicht zweimal feuert (sonst später Doppelbuchung).
3. **Vereinfachung `due_at`:** statt KONZEPTs vagem `due_window` führt S1 einen einzelnen
   `due_at`-Zeitpunkt (nullable). Reicht für die Liste „offene Aufgaben"; ein Fenster kann additiv
   folgen, falls Scheduling es braucht.

`task.completed` trägt `points` + `done_by` + `instance_id` und ist die **publizierte Vertrags-Naht**:
der Ledger-Slice abonniert dieses Event und bucht, **ohne** die tasks-Tabellen zu lesen (Modulgrenzen).

## Konsequenzen

- **Positiv:** kein verfrühter Offline-Bau (YAGNI — S1 schreibt Aufgaben nicht offline); konsistent mit
  dem etablierten, getesteten If-Match-Pfad (recipes/accounts); serverautoritative Erledigung schützt
  die spätere Ökonomie-Invariante; Doppel-Erledigung ist durch If-Match + 409 ausgeschlossen.
- **Negativ / Kosten:** zwei Schreibmodelle im System (bewusst, getrennt nach „offlinefähig?"). Werden
  Aufgaben später offline-abhakbar (mobile), ist eine additive Migration auf den Sync-Batch möglich,
  aber Arbeit (Feldgruppen + Outbox-Client) — die Erledigung müsste dann serverautoritativ bleiben.
- **Auswirkungen:** Standard-`HouseholdScoped` + Trigger, kein RLS-Sonderfall (Migration 0023,
  `household_isolation`). OpenAPI additiv. S1 fasst das Ledger **nicht** an.

## Bewusst verschoben (Folge-Slices, hier nur dokumentiert)

Punkte-Ledger/jede Buchung; RRULE-Autogenerierung + Scheduler; Rotation-Durchsetzung
(`fair|fixed|open` wird nur gespeichert); `pool`; `rooms`/`room_id`/Verfalls-Heatmap; Marketplace;
`activation_json`/Aktionsketten; `expired`-Auto-Übergang per Worker; Kinder-Wochenziele. Die verschobenen
Spalten (`rrule`, `pool`, `room_id`) werden als **additiv-nullable** in ihren eigenen Slices ergänzt
(sauberer expand/contract), nicht leer vorab angelegt.

## Alternativen (verworfen, mit Begründung)

- **Sync-Batch jetzt** — der Endzustand für offlinefähige Entitäten, aber S1 schreibt Aufgaben nicht
  offline; LWW würde zudem eine Erledigung gefährlich „mergen". Verworfen (YAGNI + Korrektheit).
- **Erledigen als Feld-PATCH (`status=done`)** — würde client-gesetzte `done_by`/`done_at` einladen und
  die Idempotenz allein dem ETag überlassen. Eine explizite Aktion + 409-Wächter ist robuster. Verworfen.
- **Hard-Delete für Instanzen** — zerstört die Historie, die der Ledger/das Fairness-Konto später
  brauchen. Verworfen (Status-Maschine statt Löschen).
