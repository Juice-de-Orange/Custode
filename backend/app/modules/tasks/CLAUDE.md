# CLAUDE.md — Modul `tasks`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Haushaltsaufgaben (KONZEPT §5.9): Task-Templates (Definition) erzeugen Task-Instanzen (konkrete
Erledigung mit Status). Fundament für Gamification/Punkte-Ledger, Marketplace und Scheduling
(spätere Slices). P4-S1 = Templates + Instanzen + Erledigen-Zustandsmaschine.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul. Quermodul nur über Domain-Events oder
  `modules/<x>/api.py`. Liest **keine** fremden Tabellen (insb. nicht `accounts`, um `assigned_to`/
  `done_by` zu validieren — die user_id wird wie angegeben/aus dem Principal gespeichert).
- Jede Fachzeile (`task_templates`, `task_instances`) trägt `household_id`; RLS aktiv (`FORCE`),
  Negativtest pro Tabelle. `household_id` kommt aus dem Principal/RLS, nie aus einem Cross-Modul-Import.

## RLS (Migration 0023)
- `task_templates` / `task_instances`: `household_id = app.household_id` (USING + WITH CHECK).
- Negativtest: Haushalt A ↛ Haushalt B → 0 Zeilen (`test_tasks_rls.py`).

## Schreibpfad
- **PATCH + If-Match** (ADR-0034): `version` (Mixin-Spalte, Trigger-bumped) ist der ETag; 412 bei
  stale, 428 bei fehlend (`kernel/http/conditional.py::parse_if_match`). **Kein Sync-Batch** in S1
  (Aufgaben online-first; Erledigung muss serverautoritativ sein).
- **Erledigen** = dedizierte Aktion `POST /instances/{id}/complete` (kein Feld-PATCH):
  Zustandsmaschine `open → done`, stempelt `done_by`/`done_at` serverseitig; If-Match + 409-Wächter
  (Status ≠ `open`) schließen Doppel-Erledigung aus.
- **Gutschrift + Wert-Verfall (ADR-0035/0036):** beim Erledigen bucht `tasks` synchron via
  `economy.api` den **effektiven** Punktwert `effective_points(base, due_at, now)` (`tasks/decay.py`:
  −10 %/Tag überfällig, Floor 50 %) und hält ihn als `awarded_points` fest. Kein Saldo-Abzug (KONZEPT §5.9).

## Schnittstellen (HTTP)
- `/v1/tasks/templates`: `GET` (Liste) · `POST` (anlegen, **admin**, CSRF, 201) · `GET {id}` (+ETag) ·
  `PATCH {id}` (**admin**, If-Match, CSRF) · `DELETE {id}` (**admin**, Soft-Delete, CSRF, 204).
  Templates tragen optional `room_id` (P4-S6).
- `/v1/tasks/instances`: `GET ?status=open|done|expired|all` (Liste, default open) ·
  `POST` (anlegen, **member+**, CSRF, 201; aus Template → Snapshot title/points, oder ad-hoc) ·
  `GET {id}` (+ETag) · `POST {id}/complete` (**member/child**, If-Match, CSRF; `open→done`, 409 sonst).
- **Räume + Heatmap (P4-S6):** `/v1/tasks/rooms` (`GET` · `POST`/`PATCH`(If-Match)/`DELETE` = **admin**)
  + `GET /v1/tasks/heatmap` (berechnete Frische je Raum: grün/gelb/rot = f(letzte Erledigung,
  `decay_days`); **nie gespeichert**, `tasks/heatmap.py::room_status`).
- **Heatmap-Aktion (P5-S11, S-13, ADR-0049):** Instanzen tragen optional `room_id` (0041) — eine ad-hoc
  Aufgabe gehört direkt einem Raum. Effektiver Raum = `COALESCE(instance.room_id, template.room_id)`;
  `room_last_done` zählt beide, sodass eine direkte Erledigung den Raum grün macht.
- **Services (`api.py`):** `create_template`, `list_templates`, `get_template`, `update_template`,
  `delete_template`, `create_instance`, `list_instances`, `get_instance`, `complete_instance`,
  `reassign_instance` (marketplace), `release_assignments_of` (Austritt, 11-S1b — offene
  Zuweisungen einer ausscheidenden Person auf `NULL`; `assigned_to` hat keinen Fremdschlüssel,
  eine stehengebliebene ID sähe für alle aus wie „vergeben", tauchte aber in keiner Liste mehr
  auf. Erledigte Instanzen bleiben unberührt — `done_by` ist Historie),
  `create_personal_task` (capture), und für Aktionsketten (P4-S9b):
  `create_armed_task` (vorgemerkte Folge-Aufgabe, `status='armed'` + `activation_json`) +
  `activate_on_item_checked` (`armed → open`, vom capture-Handler auf `shopping.item.checked` gerufen) +
  `count_open_tasks(household_id, now)` → `(open, overdue)` für den Wochen-Digest (P8-S7): filtert
  `household_id` **explizit** (Aufrufer läuft unter maint, RLS trägt nicht).

## Events
- **publiziert:** `task.created`, `task.updated`, `task.deleted` (Templates),
  `task_instance.created`, `task.completed` (Instanz erledigt) — transactional outbox
  (`kernel/events/emit.py`); SSE-Invalidation via `handlers.py` (`task.* → entity "tasks"`).
  `task.completed` trägt `points` + `done_by` + `instance_id` als Vertrags-Naht für den Ledger-Slice.
  **abonniert:** — (der Punkte-Ledger hört ab dem Folge-Slice auf `task.completed`).

## No-Gos (S1)
- **Niemals ins Punkte-Ledger schreiben / keinen Saldo berechnen** (§5.9-Invariante: amount > 0,
  keine negativen Salden). `points` ist eine inerte Spalte (`CHECK >= 0`); der einzige Output ist
  `task.completed`. Wer hier bucht, verletzt ADR-0034.
- **Kinder dürfen erledigen, aber keine Templates/Instanzen anlegen** (KONZEPT „Kinder & Sicherheit"):
  Templates = `AdminPrincipal`, Instanz-Erstellung = `require_role(admin, member)`.
- **Keine Hard-Deletes für Instanzen** (Status-Maschine statt Löschen; Historie bleibt für Ledger/
  Fairness). Template-Löschung kaskadiert nicht auf Instanzen.
- Verschoben (nicht in S1 bauen): RRULE-Autogenerierung, Rotation-Durchsetzung, `pool`, `rooms`/
  Heatmap, Marketplace, Aktionsketten, `expired`-Auto-Übergang.
