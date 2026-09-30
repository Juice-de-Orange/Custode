# CLAUDE.md — Modul `links`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Generische, **richtungsunabhängige** Verknüpfungen zwischen beliebigen Objekten (KONZEPT §5.12):
Rezept↔Anleitung, Aufgabe↔Anleitung, Notiz↔Anleitung … P7-S8 = Fundament: zwei `(type, id)`-Endpunkte
+ `relation`. **P7-S19 = Objekt-Picker (Web)**: Ziel per Namens-Dropdown statt roher UUID (reine
Frontend-Komposition über die bestehenden Listen-Endpunkte; kein Backend-Change). ACL / Anhänge =
spätere Slices.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „links must not depend on other
  modules"). Quermodul nur über Domain-Events (`link.*`) — `links.api` ist leer, kein Modul importiert
  `links`.
- Beide Endpunkte sind **nacktes UUID + String-Typ, kein FK** — `links` kennt die verknüpften Module
  nicht.
- Jede Fachzeile (`object_links`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest.

## Kanonisierung (ADR-0066)
- Endpunkte werden serverseitig geordnet (kleinerer `(type, str(id))` → `src`). `(a,b)` und `(b,a)`
  ergeben **eine** Zeile; Partial-Unique-Index verhindert symmetrische Duplikate. Re-Link = idempotent
  (liefert bestehende Zeile). Selbst-Link → 422.

## RLS (Migration 0049, ADR-0066)
- `object_links`: `household_id = app.household_id` (USING + WITH CHECK) + FORCE + Versions-Trigger.
- Negativtest: Haushalt A ↛ Haushalt B → 0 Zeilen.

## Schnittstellen (HTTP, `/v1/links`)
- `GET ?object_type=&object_id=` (member, alle Links die das Objekt berühren, älteste zuerst) ·
  `POST` (member/admin, CSRF, 201, idempotent) · `DELETE {id}` (member/admin, CSRF, 204, Soft-Delete).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `link.created`, `link.deleted` → SSE-Entity `"links"`.
- **abonniert (via Composition-Root-Handler, P7-S20):** `recipe.deleted`/`note.deleted`/`guide.deleted`
  → `service.purge_for_object` (Reaper: Links mit dem gelöschten Objekt an **einem** Endpunkt
  soft-deleten). Handler in `handlers.py`, **am Worker-Composition-Root registriert** (`app/worker.py`)
  — nie im Kernel (`kernel ↛ modules`). Event nur **per Name** gematcht (String-Map) → kein
  Fremdmodul-Import; eigene `scoped_session`; idempotent.

## No-Gos
- **Keinen** FK auf fremde Tabellen legen (generische `(type, id)`-Endpunkte).
- `links` importiert **kein** anderes Modul; Reaktion nur über `link.*`-Events.
- Endpunkte nie ungeordnet speichern (sonst symmetrische Duplikate) — immer `_canonical`.
