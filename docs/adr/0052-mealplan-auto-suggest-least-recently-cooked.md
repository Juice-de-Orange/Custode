# ADR-0052 — Auto-Vorschlag („neu würfeln"): least-recently-cooked als reine Funktion

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S4
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5.4: Der Mealplanner soll Slots **automatisch befüllen** können und ein „neu würfeln" anbieten.
Der erste, deterministische Baustein dafür ist eine **Wiederholungs-Sperre**: ein Rezept, das kürzlich
gekocht wurde, soll nicht sofort wieder vorgeschlagen werden. P6-S3 hat dafür bereits die Datenbasis
gelegt (`recipes.last_cooked_at`, gepflegt über `recipes.api.mark_cooked`, ADR-0051). Zu entscheiden:
Wie wird der Vorschlag berechnet, und wie greift er in den Slot-Schreibpfad ein?

## Entscheidung
1. **Auswahl = reine Funktion** `pick_least_recently_cooked(candidates, *, now, lockout_days,
   exclude_ids)` in `mealplanner/suggest.py` — **ohne DB, ohne LLM, deterministisch**, voll
   unit-getestet (kein Testcontainer nötig → läuft lokal ohne Docker). Regeln:
   - Rezepte, die **innerhalb `lockout_days`** vor `now` gekocht wurden (`last_cooked_at`), fallen raus
     (Wiederholungs-Sperre).
   - `exclude_ids` (bereits in derselben Woche verplante Rezepte inkl. der aktuellen Zelle) fallen raus
     → **Abwechslung** und „würfeln" liefert nie dasselbe Rezept wie zuvor.
   - Reihenfolge: **nie gekochte zuerst** (`last_cooked_at IS NULL`), dann **am längsten nicht gekocht**
     (ältestes `last_cooked_at`); Gleichstand deterministisch nach `id`.
   - Kein Kandidat → `None` (Service antwortet **422**, kein stilles No-Op).
2. **Service** `suggest_slot` liest die Kandidaten über `recipes.api.list_recipes` (RLS-scoped,
   enthält `last_cooked_at` seit P6-S3) und schließt die **diese Woche bereits verplanten** Rezepte aus.
   Der gewählte Treffer wird über den **bestehenden** `set_slot`-Pfad geschrieben — **kein zweiter
   Schreibpfad**, also automatisch `mealplan.updated` (Outbox → SSE) wie bei manueller Eingabe.
3. **`lockout_days` ist ein Request-Parameter** (Default 7), kein gespeicherter Wert — die
   philosophie-/haushaltsweite Konfiguration (settings_json) ist ein Folge-Slice. So bleibt S4 klein und
   die Sperre ist trotzdem sofort nutzbar/justierbar.
4. **HTTP** `POST /v1/mealplan/suggest?week_start=&day_of_week=&slot=&lockout_days=` (member/admin,
   CSRF) → setzt den Slot und gibt die **`WeekResponse`** zurück (gleiche Form wie `PUT /slot`); 422
   wenn kein Rezept übrig ist.

## Konsequenzen
- **Positiv:** Auswahllogik ist eine reine Funktion → schnell + erschöpfend testbar, ohne Docker;
  Schreibweg bleibt der eine `set_slot`-Pfad (Idempotenz/Events gratis); einseitige Modulgrenze
  gewahrt (`mealplanner → recipes.api`, schon erlaubt — **kein** neuer import-linter-Contract); keine
  Migration (rein additive Logik + Endpoint).
- **Abwägung:** `lockout_days` pro Request statt pro Haushalt ist bewusst minimal; die echte
  Constraint-Automatik (Philosophie-Profile, Slot-Regeln, mehrere Slots auf einmal „würfeln",
  Portionsfaktoren) baut in späteren Slices auf dieser Funktion auf.
- **Grenzen:** Zufalls-Varianz gibt es bewusst nicht (deterministisch least-recently-cooked) —
  „würfeln" heißt hier „nächst-fälliges Rezept", nicht echtes Zufallsziehen. Echte Streuung/Gewichtung
  ist ein Folge-Slice.
- **Erweiterung P6-S5 („Woche würfeln"):** Dieselbe reine Auswahl wird zu `suggest_many` greedy
  iteriert (jeder Treffer kommt in den Exclude-Set → distinkt) und füllt über `POST /suggest-week`
  alle **leeren** Zellen einer Mahlzeit über die Woche. **Best-effort** (kein 422): vorhandene Einträge
  bleiben, ein leerer Pool füllt nichts. Schreibweg bleibt `set_slot` (ein Pfad), keine Migration.

## Alternativen
- **Zufällige Auswahl (`random`)**: verworfen — nicht reproduzierbar testbar und ignoriert die
  „lange-nicht-gekocht"-Fairness; Streuung kommt später als bewusste Gewichtung obendrauf.
- **Sperre als gespeicherte Haushaltskonfiguration**: verschoben — gehört zu den Philosophie-Profilen
  (settings_json) eines späteren Slices; S4 hält die Sperre als justierbaren Request-Parameter.
- **Auswahl im SQL (`ORDER BY last_cooked_at NULLS FIRST LIMIT 1`)**: verworfen — `mealplanner` liest
  die recipes-Tabelle **nicht** direkt (Modulgrenze); die Kandidaten kommen über `recipes.api`, die
  Auswahl ist eine reine, testbare Funktion darüber.

**Erweiterung P9 (2026-07-30) — persönlicher Vorschlag:** Dieselben Eligibility-Regeln, andere
Sortierung. Meldet die Wearable-Naht für das anfragende Mitglied niedrige Erholung, sortiert
`pick_quickest` nach **Aufwand** statt nach zuletzt-gekocht; Rezepte ohne Zeitangabe landen hinten.
Ausschließlich über den schreibfreien `GET /v1/mealplan/suggestion` — `POST /suggest` bleibt
**signalfrei**, weil er in einen geteilten Haushalts-Datensatz schreibt und der Gesundheitszustand
einer Person dort nichts zu bestimmen hat. Begründung: ADR-0081 §9.
