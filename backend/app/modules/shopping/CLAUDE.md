# CLAUDE.md — Modul `shopping`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Einkaufsliste (KONZEPT §5.5) — die **erste offlinefähige** Entität. Schreibpfad = **Sync-Batch**
(ARCHITECTURE §10), nicht PATCH+If-Match. Free-Tier-Modul.

## Grenzen (hart)
- Importiert **nur** `kernel/*` (inkl. `kernel/sync`), nie ein anderes Modul. Quermodul nur über
  Events oder `api.py`. Jede Fachzeile trägt `household_id`; RLS aktiv + Negativtest.

## Schreibpfad = Sync-Batch (ADR-0032)
- `POST /v1/sync/shopping/batch` — Ops `[{client_op_id, entity, id, base_version, op, fields}]`.
- **LWW pro Feldgruppe** via Feld-Merge: nur die im Op vorhandenen Felder werden geschrieben.
  `shopping_item` Gruppe A = {label, qty, unit, category}, Gruppe B = {checked} → Abhaken kollidiert
  nie mit Umbenennen; spätere Ops gewinnen pro Feld.
- **Idempotenz:** `sync_client_ops` (`(household_id, client_op_id)` unique) — Replay = No-Op.
- Generische Maschinerie in `kernel/sync` (`apply_batch`, `ModuleSpec`); `shopping` deklariert nur
  seine Feldgruppen/Entities in `spec.py` (`SHOPPING_SPEC`).
- **`checked` ist ein eigenes Feld** (Konfliktarmut); Posten sind eigenständige Zeilen.
- **Server-Owner-Trigger** (S7): `reserve`→`reserved_by`, `checked`→`checked_by` — der Server stempelt
  die Owner-Spalte mit dem handelnden User (nicht client-fälschbar; `kernel/sync` `server_owner_fields`).

## RLS (Migrationen 0019/0020)
- `shopping_lists`/`shopping_items`/`shopping_basics`/`sync_client_ops`: `household_id = app.household_id`
  (USING + WITH CHECK). Negativtest A ↛ B.

## Events
- **publiziert:** `shopping.changed` (pro Batch) → SSE-Invalidation (`handlers.py` → "shopping").
  **publiziert (item-granular, P4-S9b):** `shopping.item.checked` mit `{id, user_id}`, wenn `checked`
  auf einer Op falsy→truthy kippt (deklarativ via `EntitySpec.transition_events`; der generische
  Sync-Engine bleibt domänen-agnostisch). Treibt Zuruf-Aktionsketten (capture aktiviert eine Aufgabe).
  **abonniert:** — (`mealplan.updated` → Regenerations-Vorschlag ab Phase 6).

## Öffentliche API (`api.py`)
- `apply_shopping_batch`, `pull_shopping`, `SHOPPING_SPEC` und `ensure_default_list` (P4-S9a,
  ADR-0038): liefert die Default-Liste oder legt sie **über denselben Sync-Batch-Pfad** an
  (deterministische `client_op_id`). Nur für server-originierte Posten (z. B. Zuruf-Confirm) —
  **kein zweiter Schreibpfad**, das No-Go unten bleibt gewahrt.

## No-Gos
- **Kein PATCH+If-Match** für `shopping_*` — der Sync-Batch ist der einzige Schreibpfad (ARCH §10).
- **Server-Autorität:** `checked_by`/`reserved_by`/`created_by` sind NICHT client-schreibbar.
- Keine Inventar-/Vorratslogik (Liste = editierbarer Vorschlag, KONZEPT §0).
