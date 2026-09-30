# Modul `nutrition`

**Status:** in Arbeit · **Phase:** 2 · **KONZEPT:** §5.3

## Zweck & Verantwortung
Nutrition-Pipeline als **eigener Querschnittsdienst** (bewusst nicht in `recipes` versteckt):
kanonische Zutaten (DE/EN), Einheiten/Umrechnung, Freitext-Matching. Nährwerte + `calculate` folgen
in S5. Abhängigkeit ist einseitig: **recipes → nutrition** (nie umgekehrt).

## Datenobjekte
| Tabelle | Art | Zugriff |
|---|---|---|
| `ingredients` | **GLOBALE Referenzdaten** (kein `household_id`, ADR-0031) | RLS `ENABLE` (nicht `FORCE`) + Allow-all-`SELECT`-Policy; App/Maint **nur `GRANT SELECT`** (read-only) |
| `ingredient_nutrition` | **GLOBALE Referenzdaten** (per-100g, 1:1 zu `ingredients`) | dito (Migration 0018) |

Migration **0017** (Starter-Korpus ~35 Zutaten DE/EN, `grams_per_unit` Einheit→Gramm, `aliases`) +
**0018** (`ingredient_nutrition`: per-100g kcal/Protein/Fett/KH/Zucker/Ballaststoffe, Quelle `manual`).
Kuratierung ausschließlich per Migration (Owner) — kein Runtime-Schreibpfad.

## Schnittstellen
- **HTTP:** `GET /v1/ingredients?q=` (auth) — kanonische Zutaten suchen (Mapping-/Override-UI, `IngredientOut`).
- **Services (`api.py`):**
  - `match_ingredient(session, raw_text)` → `IngredientMatch | None` — best-effort Freitext→Zutat
    (Kern `best_match` ist **pur/ohne DB**, unit-getestet).
  - `names_for(session, ids)` → `{id: name_de}` — Namensauflösung für Cross-Modul-Anzeige.
  - `search_ingredients(session, q)`.
  - `calculate(session, lines, servings)` → `NutritionResult` — per-Portion-Nährwerte (Einheiten→Gramm
    via `grams_per_unit`, per-100g × g/100; Kern `compute_nutrition`/`parse_quantity` **pur/ohne DB**;
    Konfidenz „complete"/„estimated" nach Abdeckung). Genutzt von `GET /v1/recipes/{id}/nutrition`.
- **Events:** — (Berechnung on-demand in S5; Worker-Caching optional später.)

## AuthZ-Matrix
| Route | anonym | auth | Schreibzugriff |
|---|---|---|---|
| `GET /v1/ingredients` | ✗ (401) | ✓ (alle Mitglieder, global lesbar) | — (Referenzdaten read-only) |

## Invarianten
- `ingredients` ist **read-only** für die App-Rolle (nur Owner/Migration schreibt) — ADR-0031.
- Matching ist **best-effort**: `raw_text` bleibt die Wahrheit, ein Treffer ist nur ein Vorschlag
  (der Nutzer kann mappen/überschreiben). Längerer kanonischer Name gewinnt (Spezifität).

## Tests
- `test_nutrition_match.py` — `best_match` (exakt/Prefix-Plural/Alias/Spezifität/kein Treffer) — **ohne Docker**.
- `test_recipes_http.py::test_ingredients_search` — Seed (Migration 0017) ist da + Suche (Testcontainers).
- `test_nutrition_calc.py` — `parse_quantity` + `compute_nutrition` (Gramm/Bruch/Default-Einheit/
  per-Portion/estimated) — **ohne Docker**. `test_recipe_nutrition_endpoint` — E2E (Mehl→364 kcal/Portion).

## Offene Punkte
- **P2-S4b ✅** Auto-Mapping in `recipes` (recipes → `nutrition.api`; `ingredient_name` in der Antwort;
  Web zeigt „→ Zutat"; import-linter-Contracts `recipes↛nutrition.internals`/`nutrition↛recipes`).
- **P2-S5 ✅** `ingredient_nutrition` (Migr.0018) + `nutrition.calculate` + `GET /recipes/{id}/nutrition`.
- **P2-S5b:** Web-Nährwert-Anzeige im Rezept-Detail (kcal/Makros/Konfidenz). **S3b/S6/S7** offen.
