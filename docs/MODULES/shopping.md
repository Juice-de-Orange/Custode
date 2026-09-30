# Modul `shopping`

**Status:** in Arbeit · **Phase:** 3 · **KONZEPT:** §5.5

## Zweck & Verantwortung
Einkaufsliste des Haushalts — die **erste offlinefähige** Entität. Schreibpfad = **Sync-Batch**
(ARCHITECTURE §10), nicht PATCH+If-Match. Free-Tier-Modul. Standalone in Phase 3 (manuelle Posten +
Basics); mealplan-Quelle ab Phase 6.

## Datenobjekte (Migration 0019)
| Tabelle | RLS | Notiz |
|---|---|---|
| `shopping_lists` | household_isolation (USING+WITH CHECK) | name, category_order[] (Markt-Layout) |
| `shopping_items` | household_isolation | **`checked` eigenes Feld** (Konfliktarmut); list_id-FK; source `manual\|basic\|mealplan` |
| `shopping_basics` | household_isolation | kuratierte Vorlage (label, category); Migr. 0020; 3. Sync-Entity |
| `sync_client_ops` | household_isolation | Idempotenz-Log (`(household_id, client_op_id)` unique); Reaper = S8 |

Alle household-scoped (HouseholdScoped-Mixin + Trigger); Keyset-Index `(household_id, updated_at, id)`
für den Delta-Pull (S2).

## Schreibpfad = Sync-Batch (ADR-0032)
- **`POST /v1/sync/shopping/batch`** (CSRF, member) — Ops `[{client_op_id, entity, id, base_version,
  op, fields}]`. **LWW pro Feldgruppe** via Feld-Merge (nur vorhandene Felder schreiben): Gruppe A =
  {label,qty,unit,category}, Gruppe B = {checked} → Abhaken kollidiert nie mit Umbenennen. Idempotenz
  via `sync_client_ops` (Replay = No-Op); gibt autoritativen Server-Zustand zurück. Deletes sticky.
- Generische Maschinerie: **`kernel/sync`** (`apply_batch`, `ModuleSpec`); `shopping/spec.py`
  (`SHOPPING_SPEC`) deklariert Entities + Feldgruppen.

## Schnittstellen
- **HTTP:** `POST /v1/sync/shopping/batch` (Push) · `GET /v1/sync/shopping?cursor=&limit=` (Delta-Pull,
  Tombstones, 410 resync; kein Cursor = Voll-Sync).
- **Services (`api.py`):** `apply_shopping_batch`, `pull_shopping`, `SHOPPING_SPEC`.
- **Events:** `shopping.changed` (pro Batch) → SSE-Invalidation (`handlers.py` → "shopping").

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `POST /v1/sync/shopping/batch` | ✗ (401) | ✗ (403) | ✓ | **RLS: nur eigene Zeilen** |
| `GET /v1/sync/shopping?cursor=` | ✗ (401) | ✗ (403) | ✓ | **RLS: nur eigene Zeilen** |

## Invarianten
- `checked`/`label`/… als getrennte Feldgruppen (LWW-Konfliktarmut, ADR-0032).
- **Server-Autorität:** `checked_by`/`reserved_by`/`created_by` nicht client-schreibbar.
- Kein PATCH+If-Match für `shopping_*` (Sync-Batch = einziger Schreibpfad). Keine Inventarlogik.

## Tests
- `test_sync_shopping_http.py` — **§10-LWW-Matrix** (verschiedene/gleiche Felder, delete+edit, Replay,
  Validierung) (Testcontainers).
- `test_shopping_rls.py` — RLS-Negativ (lists/items/sync_client_ops; A↛B) (Testcontainers).

## Offene Punkte
- **P3-S2 ✅** Pull `GET /v1/sync/shopping?cursor=` (Keyset-Merge über Entities, Tombstones=delete,
  `next_cursor`-High-Water-Mark, 410 resync bei ungültig/abgelaufen). **Offen:** `sync_client_ops`-Reaper
  (7-Tage-Retention) als Folge-Slice (braucht maint-Policy/-Grant).
- **P3-S3:** Web-Dexie-Offline-Engine (Outbox + Sync-Client). **P3-S4:** Web-UI (Liste).
  **P3-S5:** Basics + Schnellkatalog + Reservieren.
