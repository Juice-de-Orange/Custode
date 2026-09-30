# Modul `recipes`

**Status:** in Arbeit · **Phase:** 2 · **KONZEPT:** §5.2

## Zweck & Verantwortung
Rezeptdatenbank des Haushalts (strukturierte Rezepte: Zutaten, Schritte, Portionen, Zeiten, Tags,
Quelle). Fundament für Mealplanner (Phase 4) und Einkaufsliste (Phase 3). Spätere Slices: URL-Import
(SSRF), Nutrition, Kochmodus.

## Datenobjekte
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `recipes` | id (uuidv7); `version` = ETag (Trigger-bumped) | `household_id = app.household_id` (USING + WITH CHECK) |
| `recipe_ingredients` | id; `recipe_id`→`recipes`; **`raw_text` immer erhalten** | `household_id = app.household_id` (USING + WITH CHECK) |

Beide household-scoped (`HouseholdScoped`-Mixin), Migration **0016**, `FORCE ROW LEVEL SECURITY`,
`set_updated_and_version`-Trigger, `deleted_at`-Soft-Delete. RLS-Negativtest pro Tabelle
(`test_recipes_rls.py`: Haushalt A ↛ B → 0 Zeilen).

## Schnittstellen
- **HTTP `/v1/recipes` (`router.py`):** `GET` (Liste, `RecipeSummary`) · `POST` (anlegen, CSRF, 201,
  +ETag) · `GET {id}` (+ETag) · `PATCH {id}` (**If-Match**, CSRF; 412 stale / 428 fehlend) ·
  `DELETE {id}` (Soft-Delete, CSRF, 204). Schreibpfad = **PATCH + If-Match** (ADR-0029, kein
  Sync-Batch in Phase 2). ETag = `recipes.version`; Parser `kernel/http/conditional.py::parse_if_match`
  (geteilt mit accounts).
- **Import (`POST /v1/recipes/import`, CSRF, member):** `service.import_from_url` →
  **SSRF-Guard** `kernel/fetch.py::safe_fetch` (ADR-0030: Schema-Whitelist, DNS→Public-Validierung,
  Redirect-Cap ≤ 3, Timeout/Size-Limits) → **JSON-LD-Extraktion** (`importer.extract_jsonld_recipe`,
  stdlib) → **Draft** (`RecipeImportResponse`, NICHT gespeichert) → Web-Review → Speichern via
  `POST /v1/recipes`. `recipe-scrapers`-Fallback = S3b.
- **Services (`api.py`):** `create_recipe`, `list_recipes`, `get_recipe`, `get_ingredients`,
  `update_recipe`, `delete_recipe`.
- **Events out:** `recipe.created`, `recipe.updated`, `recipe.deleted` (P2-S1) — transactional outbox
  (`kernel/events/emit.py`); SSE-Invalidation via `kernel/events/handlers.py` (`recipe.* → "recipes"`).
  (Der Import emittiert nichts — der Draft ist nicht persistiert; das Speichern löst `recipe.created` aus.)
- **Ports:** — (Storage für Fotos + LLM für Import folgen als eigene Slices.)

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member | admin | fremder Haushalt |
|---|---|---|---|---|---|
| `GET /v1/recipes`, `GET {id}` | ✗ (401) | leer / 404 | ✓ | ✓ | **RLS: 0 / 404** |
| `POST /v1/recipes` | ✗ | ✗ (403 kein HH) | ✓ | ✓ | **immer ✗** (RLS) |
| `POST /v1/recipes/import` | ✗ | ✗ (403 kein HH) | ✓ | ✓ | n/a (kein DB-Zugriff) |
| `PATCH\|DELETE /v1/recipes/{id}` | ✗ | ✗ (403) | ✓ | ✓ | **404** (RLS) |

## Invarianten
- Jede Fachzeile trägt `household_id`; RLS aktiv + Negativtest.
- `raw_text` einer Zutat wird nie verworfen (kanonisches Mapping reversibel; `ingredient_id` ab S4).
- **Importierte Fremdrezepte bleiben strikt im Haushalt** (N-4, KONZEPT §5.2 Recht) — kein Sharing.

## Tests
- `test_recipes_rls.py` — RLS-Negativ (recipes + recipe_ingredients; A↛B; ohne Scope 0) (Testcontainers).
- `test_recipes_http.py` — CRUD-Roundtrip, **If-Match-Konflikt (412)** + -Pflicht (428), Soft-Delete→404,
  **Import→Draft** (nicht persistiert) + 422 ohne Rezept (Testcontainers PG+Redis).
- `test_fetch_ssrf.py` — **SSRF-Guard** (IP-Klassifikation, Schema-Block, DNS→Metadata-Block) — ohne Docker.
- `test_importer.py` — JSON-LD-Extraktion (Standard, `@graph`, String-Instructions, kein/Malformed) — ohne Docker.

## Offene Punkte
- **P2-S2 ✅** Web (Galerie/Detail/Editor) · **P2-S3 ✅** URL-Import (SSRF-Guard + JSON-LD + Review).
- P2-**S3b** `recipe-scrapers`-Fallback (Site-spezifisch, breitere Abdeckung); P2-S4/S5 Nutrition;
  P2-S6 Kochmodus; P2-S7 Seed + Fotos (Storage-Adapter MinIO).
