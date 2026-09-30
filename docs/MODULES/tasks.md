# Modul `tasks`

**Status:** in Arbeit · **Phase:** 4 · **KONZEPT:** §5.9

## Zweck & Verantwortung
Haushaltsaufgaben des Haushalts (KONZEPT §5.9): **Task-Templates** (wiederverwendbare Definition mit
Titel, Punktwert, Dauer, innen/außen, Rotations-Modus) erzeugen **Task-Instanzen** (konkrete Erledigung
mit Status). Fundament für die Punkte-Ökonomie/Gamification, den Marketplace (§5.10) und das Scheduling
(§5.8) — alles **spätere Slices**. P4-S1 = Templates + Instanzen + Erledigen-Zustandsmaschine; **kein
Punkte-Ledger**, keine Rotation/RRULE/Räume/Marketplace.

## Datenobjekte (Migration 0023)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `task_templates` | id (uuidv7); `version` = ETag (Trigger-bumped); `points` inert + `CHECK (>= 0)`; `rotation ∈ {fair,fixed,open}` (nur gespeichert) | `household_id = app.household_id` (USING + WITH CHECK) |
| `task_instances` | id; `template_id?`→`task_templates`; **Status-Maschine** `status ∈ {open,done,expired,armed}`, nie hard-deleted; `title`/`points` Snapshot; `awarded_points` (verfallene Gutschrift, 0026); `done_by`/`done_at` serverseitig; `room_id?` (direkter Raum für ad-hoc Tasks, 0041, S-13) | `household_id = app.household_id` |
| `rooms` (0027) | Raum/Zone mit `decay_days`; `version`=ETag; Soft-Delete. `task_templates.room_id`→`rooms` (optional). **Heatmap berechnet** (nie gespeichert); effektiver Raum einer Instanz = `COALESCE(instance.room_id, template.room_id)` (S-13) | `household_id = app.household_id` |

Beide household-scoped (`HouseholdScoped`-Mixin), Migration **0023**, `FORCE ROW LEVEL SECURITY`,
`set_updated_and_version`-Trigger, `deleted_at`-Soft-Delete. RLS-Negativtest pro Tabelle
(`test_tasks_rls.py`: Haushalt A ↛ B → 0 Zeilen; WITH CHECK gegen Fremd-`household_id`).
Verschoben (additiv in Folge-Slices): `rrule`, `pool`, `room_id`.

## Schnittstellen
- **HTTP `/v1/tasks/templates` (`router.py`):** `GET` (Liste, `TaskTemplateSummary`) · `POST` (anlegen,
  **admin**, CSRF, 201, +ETag) · `GET {id}` (+ETag) · `PATCH {id}` (**admin**, **If-Match**, CSRF;
  412 stale / 428 fehlend) · `DELETE {id}` (**admin**, Soft-Delete, CSRF, 204; keine Kaskade auf Instanzen).
- **HTTP `/v1/tasks/instances`:** `GET ?status=open|done|expired|all` (Liste, default `open`) ·
  `POST` (anlegen, **member+**, CSRF, 201, +ETag; aus Template → Snapshot `title`/`points`, oder ad-hoc
  mit `title`) · `GET {id}` (+ETag) · `POST {id}/complete` (**member/child**, **If-Match**, CSRF;
  `open→done`, stempelt `done_by`/`done_at`; **409** wenn nicht `open`). Schreibpfad = **PATCH + If-Match**
  (ADR-0034, kein Sync-Batch). ETag = `…​.version`; Parser `kernel/http/conditional.py::parse_if_match`.
- **Services (`api.py`):** `create_template`, `list_templates`, `get_template`, `update_template`,
  `delete_template`, `create_instance`, `list_instances`, `get_instance`, `complete_instance`,
  `reassign_instance`, `release_assignments_of`, `instance_status`.
  **`instance_status` (seit 2026-08-03) gibt `open`/`done`/`expired` oder `None` zurück** — es
  existiert, damit ein Aufrufer **fragen** kann, statt einen 404 zu fangen. `get_instance` beantwortet
  „nicht da" mit einer `ProblemException`, und wer daraus Kontrollfluss macht, entscheidet an einem
  HTTP-Status statt an der Sache. Der Austrittspfad braucht die echte Antwort: er muss wissen, ob
  geliefert wurde, **bevor** er einen Handel auflöst — und darf nicht daran sterben, dass die
  Aufgabe inzwischen weg ist (BUGLOG 2026-08-03).
- **Events out:** `task.created`, `task.updated`, `task.deleted` (Templates), `task_instance.created`,
  `task.completed` (Instanz erledigt) — transactional outbox (`kernel/events/emit.py`); SSE-Invalidation
  via `kernel/events/handlers.py` (`task.* → "tasks"`). `task.completed` trägt `points` + `done_by` +
  `instance_id` als **Vertrags-Naht** für den späteren Ledger-Slice (der bucht darauf, ohne tasks-Tabellen
  zu lesen).
- **Ports:** — (Punkte-Ledger folgt als eigener Slice; reagiert per Event, nicht per Import.)

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member | admin | child | fremder Haushalt |
|---|---|---|---|---|---|---|
| `GET templates\|instances`, `GET {id}` | ✗ (401) | leer / 404 | ✓ | ✓ | ✓ | **RLS: 0 / 404** |
| `POST\|PATCH\|DELETE /templates` | ✗ | ✗ (403) | **✗ (403)** | ✓ | **✗ (403)** | **404** (RLS) |
| `POST /instances` | ✗ | ✗ (403) | ✓ | ✓ | **✗ (403)** | **immer ✗** (RLS) |
| `POST /instances/{id}/complete` | ✗ | ✗ (403) | ✓ | ✓ | ✓ | **404** (RLS) |

Templates autorisiert nur der **Admin** (KONZEPT §5.9 „Punktwerte setzt der Admin je Template"); Kinder
dürfen **erledigen**, aber nicht autorisieren/anlegen (KONZEPT „Kinder & Sicherheit").

## Invarianten
- Jede Fachzeile trägt `household_id`; RLS aktiv + Negativtest.
- **Punkte-Nicht-Negativität (§5.9):** S1 schreibt **nie** ins Ledger; `points` ist inert (`CHECK >= 0`).
  Einziger Output der Erledigung ist `task.completed`.
- **Erledigung serverautoritativ & idempotent:** `done_by`/`done_at` setzt nur der Server; If-Match + der
  409-Wächter (Status ≠ `open`) schließen eine doppelte `task.completed`-Emission aus (sonst spätere
  Doppelbuchung). Wichtigste Korrektheits-Eigenschaft.
- **Keine Hard-Deletes für Instanzen** (Status-Maschine statt Löschen; Historie bleibt für Ledger/Fairness).
  Template-Löschung kaskadiert nicht auf Instanzen.
- `title`/`points` der Instanz sind ein **Snapshot** (späterer Template-Edit schreibt Historie nicht um).

## Tests
- `test_tasks_rls.py` — RLS-Negativ (`task_templates` + `task_instances`; A↛B → 0; WITH CHECK gegen
  Fremd-Haushalt) (Testcontainers PG18).
- `test_tasks_http.py` — Template-CRUD + **If-Match (412/428)**, Instanz aus Template (Snapshot) + ad-hoc,
  **complete → done + `task.completed`-Event** (Outbox), **Doppel-complete → 409**, Filter `?status`,
  Rollen-Guards (member ↛ Template, member ✓ Instanz/complete) (Testcontainers PG+Redis).
- Web: `task-row.test.tsx` (Erledigt-Aktion trägt ETag, Punkte/Badge), `realtime-map.test.ts`
  (`tasks → TASKS_QUERY_KEY`).

## Offene Punkte (Folge-Slices)
- **P4-S2** Punkte-Ledger (Double-Entry) — abonniert `task.completed`, bucht `points` an `member:<done_by>`.
- **P4-S3+** Rotation-Durchsetzung (`fair|fixed|open`), RRULE-Autogenerierung + Scheduler, `pool`,
  `rooms`/Verfalls-Heatmap, Marketplace (Escrow/Auto-Accept), Aktionsketten, `expired`-Auto-Übergang.
