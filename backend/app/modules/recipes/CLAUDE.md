# CLAUDE.md — Modul `recipes`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Rezeptdatenbank des Haushalts (KONZEPT §5.2): strukturierte Rezepte (Zutaten, Schritte, Portionen,
Zeiten, Tags, Quelle), Import per Link, Kochmodus. Fundament für Mealplanner (Phase 4) und
Einkaufsliste (Phase 3).

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul. Quermodul nur über Domain-Events oder
  `modules/<x>/api.py`. Liest **keine** fremden Tabellen.
- Jede Fachzeile (`recipes`, `recipe_ingredients`) trägt `household_id`; RLS aktiv (`FORCE`),
  Negativtest pro Tabelle. `household_id` kommt aus dem Principal/RLS, nie aus einem Cross-Modul-Import.

## RLS (Migration 0016)
- `recipes` / `recipe_ingredients`: `household_id = app.household_id` (USING + WITH CHECK).
- Negativtest: Haushalt A ↛ Haushalt B → 0 Zeilen (`test_recipes_rls.py`).

## Schreibpfad
- **PATCH + If-Match** (ADR-0029): `version` (Mixin-Spalte, Trigger-bumped) ist der ETag; 412 bei
  stale, 428 bei fehlend (`kernel/http/conditional.py::parse_if_match`). **Kein Sync-Batch** in
  Phase 2 (Rezepte online-first; Sync-Batch ab Phase 3, Einkaufsliste).

## Schnittstellen (HTTP, Phase 2)
- `/v1/recipes`: `GET` (Liste) · `POST` (anlegen, CSRF, 201) · `GET {id}` (+ETag) ·
  `PATCH {id}` (If-Match, CSRF) · `DELETE {id}` (Soft-Delete, CSRF, 204).
- `POST /v1/recipes/import` (CSRF, member): SSRF-Guard `kernel/fetch.py` → JSON-LD-Extraktion
  (+ `recipe-scrapers`-Fallback auf demselben HTML, P2-S3b) → Draft
  (nicht gespeichert), Review im Web (ADR-0030).
- `PUT/GET/DELETE /v1/recipes/{id}/photo` (CSRF, member, multipart): Foto via `kernel/storage`-Adapter;
  Upload normalisiert (`kernel/images`: JPEG-Re-Encode → EXIF/GPS-Strip), 503 wenn Storage aus. Bytes
  im Blob-Storage, nur `photo_key` in der DB (ADR-0033).
- **Services (`api.py`):** `create_recipe`, `list_recipes`, `get_recipe`, `get_ingredients`,
  `update_recipe`, `delete_recipe`, `mark_cooked` (P6-S3: „zuletzt gekocht"-Historie, vom Mealplanner
  einseitig aufgerufen — `last_cooked_at`/`cooked_count`, Migration 0043, ADR-0051; emittiert
  `recipe.updated`), `recipe_macros` (P6-S10/ADR-0056: pro-Portion-Makros als recipes-eigenes
  `RecipeMacros`-Value-Object — wrappt `nutrition.api.calculate`, damit der Mealplanner die
  Wochen-Nährwerte summieren kann, **ohne** `nutrition` zu importieren).

## Events
- **publiziert:** `recipe.created`, `recipe.updated`, `recipe.deleted` (P2-S1) — transactional outbox
  (`kernel/events/emit.py`); SSE-Invalidation via `handlers.py` (`recipe.* → entity "recipes"`). Der
  Import emittiert nichts (Draft nicht persistiert; das Speichern löst `recipe.created` aus).
  **abonniert:** — (Nutrition-Handler hört ab P2-S5 auf `recipe.*`).

## No-Gos
- **Importierte Fremdrezepte NIE haushaltsübergreifend teilen** (N-4, KONZEPT §5.2 Recht; RLS).
- **LLM-Output nie direkt persistieren** — Schema-Validierung + Review-Screen (ARCHITECTURE §16).
- Fremde URLs nur über den **SSRF-Guard** (`kernel/fetch.py`, P2-S3) abrufen (DNS-Pinning,
  Schema-Whitelist, Limits, Redirect-Cap).
- `raw_text` einer Zutat nie verwerfen (Mapping ist reversibel).
