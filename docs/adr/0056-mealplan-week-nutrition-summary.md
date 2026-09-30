# ADR-0056 — Wochen-Nährwert-Übersicht: Aggregation über recipes.api.recipe_macros

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 6 / P6-S10
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Das Phase-6-Ziel ist „Auto-Wochenpläne erfüllen Nährwertziele ±10 %". Voraussetzung dafür ist, dass
der Mealplanner die **Nährwerte einer geplanten Woche** kennt. Die Nutrition-Pipeline existiert bereits
(`nutrition`-Modul: kanonische Zutaten, `calculate`); `recipes` mappt Zutaten beim Anlegen auf
kanonische IDs und berechnet pro-Portion-Nährwerte (`GET /recipes/{id}/nutrition`). Offen: Wie kommt der
Mealplanner an die Nährwerte, **ohne** die Modulgrenzen zu verletzen?

## Entscheidung
1. **Neue Naht `recipes.api.recipe_macros(session, *, recipe_id) -> RecipeMacros | None`** — wrappt
   dieselbe Berechnung wie der Rezept-Nährwert-Endpunkt (`get_recipe` + `get_ingredients` +
   `nutrition.api.calculate`). Rückgabe ist ein **recipes-eigenes** Value Object `RecipeMacros`
   (kcal/protein/fat/carbs/confidence) — bewusst **nicht** `nutrition.NutritionResult`, damit der
   Aufrufer (Mealplanner) **nicht** `nutrition` importieren muss. `None`, wenn das Rezept weg ist.
2. **Mealplanner aggregiert über `recipes.api`** (`mealplanner → recipes.api` ist seit P6-S1 erlaubt —
   **kein** neuer import-linter-Contract, **kein** `nutrition`-Import im Mealplanner). Die Summierung
   ist eine **reine Funktion** `nutrition.py::sum_macros` (DB-frei, deterministisch, unit-getestet):
   summiert die pro-Portion-Makros je Rezept-Slot, zählt die Mahlzeiten, und markiert `confidence`
   `estimated`, sobald **ein** Rezept unvollständige Daten hatte.
3. **HTTP:** `GET /v1/mealplan/nutrition?week_start=` → `WeekNutrition {kcal, protein_g, fat_g,
   carbs_g, meals_counted, confidence}`. Freitext-Slots zählen nicht. Read-only, kein CSRF.
4. **Eine Portion je Rezept-Slot** in S10 (keine personenbezogenen Portionsfaktoren) — die
   Skalierung auf Haushaltsgröße/Personen-Faktoren ist ein Folge-Slice; die Naht (`recipe_macros` +
   `sum_macros`) bleibt dieselbe.

## Konsequenzen
- **Positiv:** macht die Wochen-Nährwerte sichtbar (Fundament fürs Nährwert-Ziel-Matching) ohne
  Modulgrenzen-Bruch (kein `nutrition`-Import im Mealplanner; recipes besitzt das Value Object); reine,
  testbare Aggregation; keine Migration; nutzt die bestehende, getestete Nutrition-Berechnung.
- **Abwägung (E9):** „je Rezept = eine Portion" ist eine bewusste Vereinfachung — ohne Personen-/
  Portionsfaktoren ist die Summe „pro-Portion summiert", nicht „Haushalts-Tagesbedarf". Klar im
  Feldnamen/Text kommuniziert (`per portion, summed`). `confidence=estimated` macht Datenlücken
  transparent (fehlende Zutaten-Mappings/Mengen).
- **Grenzen:** N+1-Aufrufe (`recipe_macros` je Slot) — für eine Woche (≤28 Slots) vernachlässigbar;
  eine Batch-Variante ist später möglich. Keine Zielwert-Bewertung/Optimierung in S10 (nur Anzeige).

## Erweiterung P6-S11 — ±10%-Ziel-Bewertung
Reine Funktion `nutrition.py::evaluate_target(kcal, target_kcal, tolerance=0.1) -> under|on_target|over`
(KONZEPT §5.4 „Nährwertziele ±10 %"): klassifiziert einen kcal-Wert gegen ein Ziel; ein nicht-positives
Ziel gilt als `on_target` (kein Ziel). Der `GET /nutrition`-Endpunkt nimmt **optional** `target_kcal`
(Query) und bewertet den **pro-Portion-Durchschnitt** (`kcal / meals_counted`); Antwortfelder
`target_kcal` + `verdict` bleiben `null`, wenn kein Ziel übergeben oder nichts gezählt wurde. Das Ziel ist
ein **Request-Parameter** (wie `lockout_days`) — persistente Personen-/Haushalts-Profile (settings_json)
sind ein Folge-Slice. `evaluate_target` ist das Bewertungs-Primitiv, das der Auto-Planer wiederverwendet.

## Alternativen
- **`nutrition.NutritionResult` direkt durch `recipes.api` reichen:** verworfen — der Mealplanner müsste
  den `nutrition`-Typ importieren (verbotene Abhängigkeit); das recipes-eigene `RecipeMacros` kapselt das.
- **Mealplanner → `nutrition.api` direkt:** verworfen — der Mealplanner kennt keine kanonischen Zutaten/
  Zutaten-Zeilen; die Berechnung gehört zu `recipes` (es besitzt die Zutaten). Eine zusätzliche
  Modulabhängigkeit wäre unnötig.
- **Nährwerte in `WeekResponse` einbetten:** verworfen — teure Berechnung in jeden Wochen-GET ziehen;
  ein eigener, gezielt abrufbarer Endpunkt ist günstiger (das Grid braucht die Summe nicht immer).
