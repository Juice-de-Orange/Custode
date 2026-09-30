# CLAUDE.md — Modul `nutrition`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Nutrition-Pipeline als **eigener Querschnittsdienst** (KONZEPT §5.3, bewusst nicht in `recipes`
versteckt): kanonische Zutaten (DE/EN), Einheiten/Umrechnung (`grams_per_unit`), Freitext-Matching;
Nährwerte + `calculate` folgen in S5.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul. Andere Module nutzen `nutrition` **nur über
  `api.py`** (`match_ingredient`, `names_for`, `search_ingredients`). `nutrition` importiert **nie**
  `recipes` (Abhängigkeit ist einseitig: recipes → nutrition).
- `nutrition` liest **keine** Rezept-Tabellen. Für die Berechnung (S5) bekommt es die Zutaten-Zeilen
  vom Aufrufer übergeben — kein Cross-Modul-Tabellenzugriff.

## Datenobjekte
- **`ingredients` — GLOBALE Referenzdaten (kein `household_id`, ADR-0031).** RLS `ENABLE` (nicht
  `FORCE`) + Allow-all-`SELECT`-Policy; App-/Maint-Rolle nur `GRANT SELECT` (read-only). Kuratiert per
  Migration (Owner). Migration **0017** (Starter-Korpus ~35). `grams_per_unit` = Einheit→Gramm;
  `aliases` für Matching.

## Schnittstellen
- **HTTP:** `GET /v1/ingredients?q=` (auth) — kanonische Zutaten suchen (Mapping-/Override-UI).
- **Services (`api.py`):** `match_ingredient(session, raw_text)` → `IngredientMatch | None`
  (best-effort, `best_match` ist pur/testbar); `names_for(session, ids)` → `{id: name_de}`;
  `search_ingredients(session, q)`.

## No-Gos
- Keine `household_id`/RLS-Pflicht für `ingredients` (Referenzdaten, ADR-0031) — aber **read-only**
  für die App-Rolle; Schreibzugriff nur Owner/Migration.
- `nutrition` darf `recipes` (oder ein anderes Modul) **nicht** importieren.
- Matching ist best-effort — `raw_text` bleibt die Wahrheit; ein Treffer ist nur ein Vorschlag.
