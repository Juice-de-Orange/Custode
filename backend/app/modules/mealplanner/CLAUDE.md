# CLAUDE.md — Modul `mealplanner`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Wochenplanung des Essens (KONZEPT §5.4). P6-S1 = manueller Wochenplan: ein Rezept **oder** Freitext je
Tag/Mahlzeit, plus „wer kocht". Automatik/Philosophie-Profile/Slot-Regeln = spätere Slices.

## Grenzen (hart)
- Importiert **nur** `kernel/*` + `recipes.api` (Titel + `recipe_macros` für die Wochen-Nährwerte,
  P6-S10/ADR-0056 — **nicht** `nutrition` direkt) + `shopping.api` (Einkaufslisten-Generierung über
  den Sync-Batch, §5.5) + `tasks.api` (Koch-Task aus Slot, S-03, ADR-0053) + `calendar.api`
  (Abwesenheits-Hinweis, S-01, ADR-0054) (import-linter: „mealplanner uses only recipes/shopping/
  tasks/calendar public api"). **Nie** deren Interna oder ein anderes Modul. Kein Modul importiert
  `mealplanner` (einseitig). `api.py` ist leer — Quermodul-Reaktion läuft über das **Event**
  `mealplan.updated`; die synchronen `*.api`-Aufrufe sind read-only Hinweise oder explizite Aktionen.
- Jede Fachzeile (`meal_plans`, `meal_slots`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest je
  Tabelle.

## Datenmodell (Migration 0042, ADR-0050)
- `meal_plans`: `week_start` (Montag der ISO-Woche; unique pro Haushalt+Woche).
- `meal_slots`: `plan_id`, `day_of_week` 0–6, `slot ∈ {breakfast,lunch,dinner,snack}`, `recipe_id?`
  **oder** `free_text?` (XOR, validiert), `cook_id?`, `note?`; unique pro (plan, day, slot).

## Rezept-Referenz
- `recipe_id` ist ein **nacktes UUID — kein DB-FK**. Titel-Auflösung über `recipes.api.list_recipes`;
  gelöschtes Rezept → `recipe_title = None` (dangelt weich). **Nie** einen FK auf `recipes` legen,
  **nie** die recipes-Tabelle direkt lesen.

## Schreibpfad & Wochen-Identität
- Endpoints normalisieren jedes In-Woche-Datum auf den **Montag** (`_monday`) — `?week_start=<beliebig>`
  trifft denselben Plan. GET einer leeren Woche legt den Plan **on demand** an (`slots: []`).
- `set_slot`/`clear_slot` emittieren **`mealplan.updated`** (Outbox → SSE-Entity `"mealplan"`). Das ist
  die Naht für die spätere **Einkaufslisten-Regeneration** — **kein** synchroner Aufruf dorthin.

## Schnittstellen (HTTP, `/v1/mealplan`)
- `GET ?week_start=` (member/admin) → `WeekResponse {week_start, slots[], absent_days[]}` (Plan on
  demand; `absent_days` = Wochentage, an denen der Betrachter laut Kalender abwesend ist, S-01).
- `PUT /slot?week_start=` (member/admin, CSRF) → Slot setzen (Rezept **oder** Freitext + cook/note).
- `POST /suggest?week_start=&day_of_week=&slot=&lockout_days=` (member/admin, CSRF) → „neu würfeln":
  füllt den Slot mit dem am längsten nicht gekochten geeigneten Rezept (reine Funktion `suggest.py`,
  Wiederholungs-Sperre über `recipes.last_cooked_at`, ADR-0052), 422 ohne Kandidat; ein Schreibpfad
  (`set_slot`). Kandidaten via `recipes.api.list_recipes` — **kein** Direktlesen.
- `POST /suggest-week?week_start=&slot=&lockout_days=&target_kcal=` (member/admin, CSRF) → „Woche
  füllen": ohne `target_kcal` least-recently-cooked (`suggest_many`, ADR-0052), mit `target_kcal` die
  Rezepte nächst am kcal-Ziel (`pick_for_target`, ADR-0057, Makros via `recipes.api.recipe_macros`).
  Distinkt, best-effort (vorhandene Einträge bleiben, leerer Pool → 200 No-Op, kein 422). `exclude_tag`
  (wiederholbar) filtert Allergen-/Diät-Tags (`filters.py::has_excluded_tag`, ADR-0058) vor der Auswahl.
- `POST /copy?week_start=&source_week=` (member/admin, CSRF) → „Woche übernehmen": kopiert die Quelle
  (default Vorwoche) in die leeren Ziel-Zellen, non-destruktiv (überschreibt nichts), über `set_slot`.
- `POST /slot/cook-task?week_start=&day_of_week=&slot=` (member/admin, CSRF, 201) → Koch-Aufgabe
  „Kochen: <Gericht>" via `tasks.api.create_personal_task` (points 0), an `cook_id` oder Caller; 422
  bei leerem Slot. Explizit (kein gespeicherter Link); volle S-03 (Punkte/Rotation) = später.
- `POST /slot/prep-task?week_start=&day_of_week=&slot=` (member/admin, CSRF, 201) → Vorbereitungs-
  Aufgabe „Vorbereiten: <Gericht> (<Hinweis>)" bei Vorlauf-Rezept (reine Heuristik `prep.py::needs_prep`
  über `recipes.api`-Steps/Tags, ADR-0055); 422 bei Freitext/leer oder ohne Vorlauf. `due_at` = später.
- `POST /slot/cooked?week_start=&day_of_week=&slot=` (member/admin, CSRF, 204) → „gekocht":
  meldet den Slot über `recipes.api.mark_cooked` an die Rezept-Historie (speist die
  Wiederholungs-Sperre aus ADR-0052) und emittiert `mealplan.cooked`; 422 `no_recipe` bei leerem
  oder Freitext-Slot — ohne Rezept gibt es nichts zuzuschreiben.
- `GET /nutrition?week_start=&target_kcal=` (member/admin) → Wochensumme der Portions-Makros
  (`recipes.api.recipe_macros` → `nutrition.api`; P6-S10). Freitext-Slots und Rezepte ohne Makros
  zählen **nicht** mit (`meals_counted` sagt, wie viele es waren); `confidence` ist nur `complete`,
  wenn jede gezählte Mahlzeit vollständig war, sonst `estimated`. Mit `target_kcal` wird der
  Portions-Schnitt ±10 % bewertet (`under|on_target|over`, P6-S11).
- `DELETE /slot?week_start=&day_of_week=&slot=` (member/admin, CSRF) → Slot leeren.
- `POST /to-shopping?week_start=` (member/admin, CSRF) → Zutaten der Wochen-Rezepte in die
  Default-Einkaufsliste (über `shopping.api` Sync-Batch, deterministische ids → idempotent),
  `source="mealplan"`. Mengen-Aggregation/Einheiten-Umrechnung (Nutrition-Pipeline) = Folge-Slice.

## Persönlicher Vorschlag (P9, ADR-0081 §9)
- `GET /v1/mealplan/suggestion` schlägt dem **Aufrufer** ein Rezept vor und **schreibt nichts**.
  Genau deshalb darf dort sein eigenes Wearable-Recovery-Signal einfließen: nur sein explizites
  `PUT /slot` ändert etwas Geteiltes (S-14 „nur für eigene Vorschläge").
- **`POST /suggest` bleibt signalfrei** — der schreibt via `set_slot` in den Haushalts-Wochenplan;
  dort würde ein Gesundheitszustand einen Haushalts-Datensatz bestimmen.
- Bei niedriger Erholung sortiert `pick_quickest` nach Aufwand statt „am längsten nicht gekocht".
  **Wiederhol-Sperre und Wochen-Ausschlüsse gelten weiter** — „du bist müde" darf nicht „iss jeden
  Tag dasselbe" werden. Rezepte ohne Zeitangabe sortieren **hinten**.

## No-Gos
- **Kein** FK/Direktlesen auf `recipes`; nur `recipes.api`.
- **Kein** synchroner Aufruf in die Einkaufsliste — nur `mealplan.updated`.
- Rezept **und** Freitext gleichzeitig → 422 (XOR).
