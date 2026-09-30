# Modul `mealplanner`

**Status:** in Arbeit · **Phase:** 6 · **KONZEPT:** §5.4

## Zweck & Verantwortung
Wochenplanung des Essens. P6-S1 ist das **manuelle Fundament**: ein Rezept **oder** ein Freitext je
Tag/Mahlzeit, plus „wer kocht". Automatik-Engine, Philosophie-Profile, Slot-Regeln, persönliche
Portionsfaktoren und die Einkaufslisten-Regeneration bauen in späteren Slices darauf auf. Importiert
**nur** `kernel/*` + `recipes.api` + `shopping.api` + `tasks.api` + `calendar.api` +
`wearables.api` (je nur die `api`-Naht); kein Modul liest seine Tabellen.

## Datenobjekte (Migration 0042)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `meal_plans` | id; `week_start` (Montag der ISO-Woche; unique pro Haushalt+Woche, partial WHERE not deleted) | `household_id = app.household_id` (USING + WITH CHECK) |
| `meal_slots` | id; `plan_id`→`meal_plans` (ON DELETE CASCADE); `day_of_week` 0–6 (CHECK); `slot ∈ {breakfast,lunch,dinner,snack}` (CHECK); `recipe_id?` (nacktes UUID, kein FK) **xor** `free_text?`; `cook_id?`; `note?`; unique pro (plan, day, slot) | `household_id = app.household_id` (USING + WITH CHECK) |

RLS-Negativtest (`test_mealplanner_rls.py`: A↛B→0, WITH CHECK) je Tabelle.

## Rezept-Referenz (ADR-0050)
`meal_slots.recipe_id` ist ein **nacktes UUID — kein DB-FK** auf `recipes` (Modulgrenze). Titel werden
beim Lesen über `recipes.api.list_recipes` (RLS-scoped) aufgelöst; ein gelöschtes Rezept „dangelt"
einfach auf `recipe_title = None`. Ein Slot ist **Rezept oder Freitext** (XOR, Pydantic-validiert → 422
bei beidem).

## Wochen-Identität & Schreibpfad
`week_start` wird serverseitig auf den **Montag** der ISO-Woche normalisiert — `?week_start=<Mittwoch>`
trifft denselben Plan. Ein GET einer leeren Woche legt den Plan **on demand** an (`slots: []`).
`set_slot`/`clear_slot` emittieren **`mealplan.updated`** (Outbox → SSE-Entity `"mealplan"`) — die
**Naht**, an der die spätere Einkaufslisten-Regeneration (KONZEPT §5.5, Diff-basiert) andockt.

## Einkaufslisten-Generierung (P6-S2, KONZEPT §5.5)
`POST /v1/mealplan/to-shopping?week_start=` sammelt die Zutatenzeilen der Wochen-Rezepte (über
`recipes.api.get_ingredients`), dedupt sie textbasiert (case-insensitiv) und schreibt sie als Posten in
die Default-Einkaufsliste — **über `shopping.api`** (`ensure_default_list` + `apply_shopping_batch`,
Sync-Batch, **kein zweiter Schreibpfad**), mit `source="mealplan"`. Die item-/op-ids werden
deterministisch aus (Woche, Label) abgeleitet → erneutes Generieren ist **idempotent** (Upsert, keine
Duplikate). Mengen-aware Aggregation + Einheiten-Umrechnung (Nutrition-Pipeline) ist ein **Folge-Slice**
— sie braucht kanonische Zutaten (`recipes.ingredient_id` ist bis dahin NULL). Rückgabe `{added: int}`.

## Auto-Vorschlag „neu würfeln" (P6-S4, ADR-0052)
`POST /v1/mealplan/suggest?week_start=&day_of_week=&slot=&lockout_days=` füllt **einen** Slot mit dem
**am längsten nicht gekochten** geeigneten Rezept und gibt die `WeekResponse` zurück (gleiche Form wie
`PUT /slot`). Die Auswahl ist eine **reine Funktion** (`suggest.py::pick_least_recently_cooked`, ohne DB/
LLM, deterministisch): Rezepte, die innerhalb `lockout_days` (Default 7) gekocht wurden, fallen raus
(Wiederholungs-Sperre über `recipes.last_cooked_at` aus P6-S3); diese Woche bereits verplante Rezepte
(inkl. der aktuellen Zelle) fallen raus (Abwechslung); Reihenfolge: **nie gekochte zuerst**, dann
ältestes `last_cooked_at`, Gleichstand nach `id`. Kein Kandidat → **422** (kein stilles No-Op). Der
Treffer wird über den **bestehenden** `set_slot`-Pfad geschrieben (ein Schreibpfad, `mealplan.updated`).
Kandidaten kommen über `recipes.api.list_recipes` (Modulgrenze — kein Direktlesen). `lockout_days` ist
ein Request-Parameter; haushaltsweite Philosophie-/Slot-Profile sind ein Folge-Slice.

`POST /v1/mealplan/suggest-week?week_start=&slot=&lockout_days=&target_kcal=` (P6-S5/S12) füllt **alle
leeren** Zellen **einer** Mahlzeit über die ganze Woche auf einmal. **Zwei Strategien:** ohne
`target_kcal` greedy least-recently-cooked (`suggest_many`, ADR-0052); mit `target_kcal` die Rezepte,
deren **pro-Portion-kcal** dem Ziel am nächsten sind (`pick_for_target`, ADR-0057, Makros über
`recipes.api.recipe_macros`). Immer distinkt, ohne bereits verplante Rezepte. **Best-effort**: vorhandene
Einträge bleiben, leerer Pool → 200 No-Op. Jeder Treffer geht über `set_slot`. Property-Test (Hypothesis):
kein verworfenes Rezept ist näher am Ziel als ein gewähltes. **Ausschluss (P6-S13, ADR-0058):** der
wiederholbare `exclude_tag`-Parameter filtert Rezepte mit Allergen-/Diät-Tags (reine `has_excluded_tag`)
**vor** beiden Strategien — kombiniert mit `target_kcal` der „±10 % **ohne** Allergie-Verstöße"-Fall.

## Wochen-Nährwert-Übersicht (P6-S10, ADR-0056)
`GET /v1/mealplan/nutrition?week_start=` summiert die **pro-Portion-Makros** der in der Woche geplanten
Rezepte → `WeekNutrition {kcal, protein_g, fat_g, carbs_g, meals_counted, confidence}`. Macros kommen
über die neue Naht `recipes.api.recipe_macros` (die intern `nutrition.api` nutzt) — der Mealplanner
importiert **nicht** `nutrition`. Summierung = reine Funktion `nutrition.py::sum_macros`. Freitext-Slots
zählen nicht; `confidence=estimated`, sobald ein Rezept unvollständige Daten hatte. Eine Portion je
Rezept-Slot (Personen-/Portionsfaktoren = Folge-Slice). **±10%-Bewertung (P6-S11):** mit optionalem
`?target_kcal=` bewertet der Endpunkt den **pro-Portion-Durchschnitt** über die reine Funktion
`evaluate_target` → Felder `target_kcal` + `verdict ∈ {under, on_target, over}` (sonst `null`). Ziel als
Request-Parameter (persistente Profile = später). Fundament fürs Phase-6-Ziel („Nährwertziele ±10 %").

## Vorbereitungs-Task am Vortag (P6-S9, Synergie S-02, ADR-0055)
`POST /v1/mealplan/slot/prep-task?week_start=&day_of_week=&slot=` legt „Vorbereiten: <Gericht>
(<Hinweis>)" an, **wenn** das Rezept des Slots Vorlauf braucht — erkannt durch die **reine Heuristik**
`prep.py::needs_prep(steps_md, tags)` (DE+EN-Cues: auftauen/marinieren/einweichen/über Nacht/… ·
thaw/marinate/soak/overnight/…). Rezeptdaten über `recipes.api.get_recipe` (kein Direktlesen); Aufgabe
über `tasks.api.create_personal_task` (points 0), an `cook_id`/Caller. **422** bei Freitext-/leerem
Slot **oder** wenn nichts vorzubereiten ist. Kein neuer Contract, keine Migration. Echte `due_at`-
Terminierung („am Vortag" als Datum) + Auto-Erzeugen beim Einplanen = Folge-Slices.

## Abwesenheits-Hinweis (P6-S8, Synergie S-01, ADR-0054)
`GET /v1/mealplan` liefert zusätzlich `absent_days: list[int]` — die Wochentags-Indizes (0-6), an denen
der **Betrachter abwesend** ist (read-only Hinweis, kein Block). Quelle: `calendar.api.list_absence_
intervals` (viewer-scoped, expandiert) → reine Mapping-Funktion `absence.py::absence_weekdays` (UTC-
Tagesgrenzen, dokumentierte Vereinfachung). Nur der GET füllt das Feld; Schreib-Endpunkte geben `[]`
(das Web holt nach Mutationen ohnehin den GET). `mealplanner` liest dafür **nur** `calendar.api` (kein
Direktlesen). Automatik (Slot überspringen, Portionen +n, „Gäste/auswärts") = Folge-Slice.

## Koch-Task aus Slot (P6-S7, Synergie S-03, ADR-0053)
`POST /v1/mealplan/slot/cook-task?week_start=&day_of_week=&slot=` legt aus einem geplanten Slot eine
**persönliche Koch-Aufgabe** „Kochen: <Gericht>" an — über `tasks.api.create_personal_task` (points 0,
einseitig, ADR-0053), zugewiesen an den Slot-`cook_id` **oder** den auslösenden Nutzer. Gericht = Rezept-
titel (über `recipes.api`) **oder** Freitext. **422** bei leerem Slot. Rückgabe `{title, assigned_to}`.
Die Aktion ist **explizit** (kein gespeicherter Slot↔Task-Link, daher bewusst nicht idempotent); die
volle S-03 (Rotation/Fairness/**Punkte fürs Kochen**/Template-Verknüpfung) ist ein Folge-Slice.

## Woche übernehmen (P6-S6)
`POST /v1/mealplan/copy?week_start=&source_week=` kopiert einen Wochenplan in die **leeren** Zellen
einer anderen Woche (`source_week` default = Vorwoche). **Non-destruktiv**: nur (Tag, Slot)-Zellen, die
im Ziel leer sind, werden aus der Quelle befüllt (Rezept **oder** Freitext + cook/note verbatim);
vorhandene Ziel-Einträge bleiben. No-op, wenn Quelle = Ziel oder die Quelle leer ist. Jede Kopie geht
über `set_slot` (ein Schreibpfad). Beide Wochen werden auf Montag normalisiert.

## Schnittstellen
- **HTTP `/v1/mealplan` (member/admin):** `GET ?week_start=` → `WeekResponse {week_start, slots[], absent_days[]}` ·
  `PUT /slot?week_start=` (Rezept **oder** Freitext + cook/note) · `DELETE /slot?week_start=&day_of_week=&slot=` ·
  `POST /suggest?week_start=&day_of_week=&slot=&lockout_days=` → `WeekResponse` (422 ohne Kandidat) ·
  `POST /suggest-week?week_start=&slot=&lockout_days=` → `WeekResponse` (best-effort, kein 422) ·
  `POST /copy?week_start=&source_week=` → `WeekResponse` (non-destruktiv, Vorwoche default) ·
  `POST /slot/cook-task?week_start=&day_of_week=&slot=` → `CookTaskResult {title, assigned_to}` (201) ·
  `POST /slot/prep-task?week_start=&day_of_week=&slot=` → `PrepTaskResult {title, assigned_to, hint}` (201) ·
  `POST /to-shopping?week_start=` → `GenerateResult {added}` ·
  `GET /nutrition?week_start=` → `WeekNutrition` (Wochen-Makros). CSRF auf Writes.
- **Cross-Modul:** importiert **nur** `kernel/*` + `recipes.api` (Titel/Zutaten/`recipe_macros`) +
  `shopping.api` (Sync-Batch-Generierung) + `tasks.api` (Koch-Task, S-03) + `calendar.api`
  (Abwesenheits-Hinweis, S-01) + `wearables.api` (`recovery_signal` — **ausschließlich** im nicht
  schreibenden `GET /suggestion`, ADR-0081 §9). **Nicht** `nutrition` (Makros laufen über
  `recipes.api`). `mealplanner.api` ist leer.
- **Events out:** `mealplan.updated` (→ Einkaufsliste, später) → SSE-Entity `"mealplan"`;
  `mealplan.cooked` (P6-S3) → SSE-Entity `"recipes"`. **Kochen-Aktion** `POST /v1/mealplan/slot/cooked`
  ruft `recipes.api.mark_cooked` **synchron** (einseitig, ADR-0051) → bumpt die „zuletzt gekocht"-
  Historie des Rezepts; 422 bei leerem/Freitext-Slot.

## Persönlicher Vorschlag (P9, ADR-0081 §9)

`GET /v1/mealplan/suggestion?week_start=&slot=&lockout_days=` (member/admin, **read-only**) →
`{recipe_id, title, total_minutes?, reasons[]}`, 404 wenn nichts qualifiziert.

Der Unterschied zu `POST /suggest` ist der Punkt: jener **schreibt** (`set_slot` +
`mealplan.updated`) und landet im geteilten Wochenplan; dieser schlägt nur vor, und erst das
explizite `PUT /slot` des Menschen ändert etwas Geteiltes. Deshalb — und nur deshalb — darf hier
das **eigene** Wearable-Recovery-Signal einfließen (S-14 „nur für eigene Vorschläge").

Bei niedriger Erholung sortiert `suggest.pick_quickest` nach Aufwand (prep+cook) statt nach „am
längsten nicht gekocht"; `reasons` wird dann `["low_recovery", "quick"]` statt
`["least_recently_cooked"]`. **Wiederhol-Sperre und Wochen-Ausschlüsse gelten unverändert** — „du
bist müde" darf nicht „iss jeden Tag dasselbe" werden. Rezepte ohne Zeitangabe sortieren hinten:
unbekannter Aufwand ist kein Beleg für geringen. Ohne Wearable/Consent/aktuelle Lesung ist das
Ergebnis exakt der Haushalts-Default.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `GET /mealplan` | ✗ (401) | ✗ (403) | ✓ | RLS: nur eigene |
| `PUT/DELETE /mealplan/slot` | ✗ | ✗ (403) | ✓ | **RLS** |
| `GET /mealplan/suggestion` | ✗ (401) | ✗ (403) | ✓ (read-only; nutzt **nur das eigene** Recovery-Signal) | RLS: nur eigener Haushalt |

## Tests
- `test_mealplanner_rls.py` — RLS-Negativ + WITH CHECK für `meal_plans` + `meal_slots` (Testcontainers).
- `test_mealplanner_suggest.py` (rein, P9 erweitert) — `pick_quickest`: kürzestes Rezept gewinnt,
  **Wiederhol-Sperre und Wochen-Ausschlüsse gelten weiter** („du bist müde" ≠ „iss jeden Tag
  dasselbe"), Rezepte **ohne** Zeitangabe sortieren hinten (unbekannter Aufwand ist kein Beleg für
  geringen), deterministischer Tiebreak.
- `test_mealplanner_http.py` (P9 erweitert) — die zwei Aussagen, auf die es ankommt:
  `test_personal_suggestion_writes_nothing` (der Aufruf verändert den geteilten Wochenplan nicht)
  und `test_a_co_members_reading_never_shapes_my_suggestion` (N-2 Ende zu Ende).
- `test_mealplanner_nutrition.py` — **reine** Unit-Tests der Makro-Summierung + Ziel-Bewertung (kein
  Docker): leer→0/complete, Summe + Zählung, estimated-Propagation, Rundung; `evaluate_target`
  (im Band/unter/über, Bandgrenzen inklusiv, Ziel≤0→on_target, eigene Toleranz).
- `test_mealplanner_prep.py` — **reine** Unit-Tests der Vorlauf-Heuristik (kein Docker): kein Cue→None,
  Auftauen/Marinieren (case-insensitiv), Cue in Tags, EN-Cues, deterministische Priorität, leer→None.
- `test_mealplanner_absence.py` — **reine** Unit-Tests des Abwesenheits-Mappings (kein Docker): Einzel-/
  Mehrtages-Span, Halb-offen an Mitternacht, außerhalb der Woche ignoriert, dedupe/sortiert, Sonntag.
- `test_mealplanner_suggest.py` — **reine** Unit-Tests der Auswahl (kein Docker): nie-gekocht zuerst,
  ältestes zuerst, Lockout (Grenze inklusiv, 0 lässt alles zu), `exclude_ids`, leer→None, det. Tiebreak;
  `suggest_many` (distinkt in Fälligkeits-Reihenfolge, Pool-erschöpft→best-effort, Lockout/Exclude, 0);
  `pick_for_target` (nächst-am-Ziel, Distanz-Ordnung, Exclude/best-effort + Hypothesis-Property-Invariante).
- `test_mealplanner_filters.py` — **reine** Unit-Tests des Ausschluss-Filters (kein Docker): normalize
  (lower/strip/blanks), leerer Ausschluss, case-insensitiver Treffer, kein Treffer, Rezept ohne Tags.
- `test_mealplanner_http.py` — leere Woche on demand; Rezept-Slot → Titel aufgelöst; Freitext + Leeren;
  Rezept+Freitext zusammen → 422; Upsert überschreibt dieselbe Zelle; Montag-Normalisierung;
  `suggest` füllt Slot, meidet bereits verplante Rezepte, 422 bei Lockout (0 lässt es wieder zu);
  `suggest-week` füllt alle 7 Tage distinkt (auch mit `target_kcal`), lässt Vorhandenes stehen, leer → No-Op;
  `copy` füllt leere Ziel-Zellen aus der Quelle (Rezept+Freitext), überschreibt nichts, leere Quelle → No-Op;
  `cook-task` legt „Kochen: <Gericht>" an (Rezept→Caller, Freitext+cook_id→cook), leerer Slot → 422;
  `prep-task` legt bei Vorlauf-Rezept „Vorbereiten: …" an (Cue im Titel), kein Vorlauf/Freitext → 422;
  `nutrition` leer → 0/complete, nach Planung Summe + `meals_counted` (Freitext zählt nicht),
  `?target_kcal=` → `verdict` (kein Ziel/0 Mahlzeiten → `null`, 0-kcal-Rezept unter 700 → „under");
  `absent_days` leer ohne Abwesenheit, markiert den Wochentag einer Kalender-Abwesenheit.

## Offene Punkte (spätere Slices)
- **Drag&Drop**, **Slots konfigurierbar**, **Philosophie-Profile + Constraint-Automatik** mit
  Klartext-Begründung (P6-S4 lieferte den ersten Baustein: deterministisches „neu würfeln" je Slot —
  Mehr-Slot-/Ganze-Woche-Würfeln, gewichtete Streuung und haushaltsweite `lockout_days`/Profile folgen),
  **Slot-Regeln**, **persönliche Portionsfaktoren**, **Einkaufslisten-Regeneration** auf
  `mealplan.updated`, Synergien S-01/02/03/07/08.
