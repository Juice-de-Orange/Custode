# ADR-0031: Referenz-/Stammdaten als globale Tabellen (RLS-Ausnahme)

- **Status:** beschlossen
- **Datum:** 2026-06-20
- **Betrifft:** `modules/nutrition` (`ingredients`), künftige Stammdaten · **Bezug:** KONZEPT §5.3, CLAUDE.md (Mandanten-Isolation)

## Kontext

Die Root-`CLAUDE.md` fordert: „jede **Fachzeile** hat `household_id`; RLS aktiv mit `FORCE`". Die
kanonische Zutaten-Liste (`ingredients`, KONZEPT §5.3) ist aber **keine Fachzeile** — sie ist
**Stamm-/Referenzdaten**, für **alle** Haushalte identisch (USDA/Open-Food-Facts-Mapping, einmal
kuratiert). Ein `household_id` + household-RLS wäre falsch (jeder Haushalt bräuchte eine Kopie; das
Matching/die Nährwerte sind global). Gleichzeitig soll die App-Rolle die Liste **nicht verändern**
können, und das „jede Tabelle hat RLS"-Posture soll erhalten bleiben.

## Entscheidung

**Referenz-/Stammdaten-Tabellen sind global (kein `household_id`) und für die App-Rolle read-only:**

- **Kein `household_id`, keine household-RLS-Policy.**
- **`ENABLE ROW LEVEL SECURITY` (nicht `FORCE`)** + eine **Allow-all-Lese-Policy**
  (`CREATE POLICY … FOR SELECT USING (true)`). So bleibt RLS auf jeder Tabelle aktiv (Posture), und der
  **Owner** kann in Migrationen seeden (ohne `FORCE` umgeht der Owner RLS).
- **`GRANT SELECT`** an `custode_app` (und `custode_maint`) — **kein** INSERT/UPDATE/DELETE. Damit ist
  die Tabelle für die App **read-only**; Kuratierung passiert ausschließlich über **Migrationen** (Owner).
- Erste Anwendung: `ingredients` (Migration 0017, Starter-Korpus ~35). Muster gilt für weitere
  Stammdaten (Kategorien, Einheiten, …).

## Konsequenzen

- **Positiv:** korrektes Datenmodell (eine globale Quelle statt Kopien pro Haushalt); App kann
  Referenzdaten nicht manipulieren (nur lesen); RLS bleibt auf allen Tabellen aktiv. Kein
  Cross-Tenant-Leak möglich (es gibt nichts Tenant-spezifisches).
- **Kosten/Hinweis:** **kein `FORCE`** bei Referenztabellen — bewusst, damit Owner-Migrationen seeden
  können; sicher, weil die App-Rolle kein Schreib-`GRANT` hat (FORCE schützt gegen App-Ownership, die
  hier nicht besteht). RLS-Negativtests (Haushalt A ↛ B) sind **nicht anwendbar**; stattdessen gilt:
  **App-Rolle hat nur SELECT** (read-only). Kuratierung nur per Migration (kein Runtime-Write-Pfad).

## Alternativen (verworfen)

- **`ingredients` household-scoped + RLS** — falsches Modell (Kopie je Haushalt; globales Matching/
  globale Nährwerte gingen verloren). Verworfen.
- **`FORCE RLS` + Allow-all-Policy** — der Owner könnte dann in Migrationen ohne INSERT-Policy nicht
  seeden (FORCE gilt auch für den Owner). Mehraufwand ohne Sicherheitsgewinn (App hat eh kein
  Schreib-Grant). Verworfen zugunsten `ENABLE` (nicht `FORCE`).
- **Gar keine RLS** — bräche das „jede Tabelle hat RLS"-Posture/Audit. Verworfen zugunsten
  `ENABLE` + Allow-all-Lese-Policy.
