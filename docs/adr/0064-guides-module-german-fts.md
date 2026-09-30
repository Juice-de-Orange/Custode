# ADR-0064 — `guides`-Modul (Anleitungen): deutsche Volltextsuche via GENERATED tsvector

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S6
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
KONZEPT §5 / Phase 7: **Anleitungen** (Markdown, Anhänge, Kategorien, **FTS deutsch**, ACL,
Ansprechpartner) + `object_links`. Wie bei den anderen Modulen wird zuerst das **Fundament** gebaut;
ACL/Anhänge/Contacts/object_links folgen. Kern-Entscheidung: wie die **deutsche Volltextsuche**
umgesetzt wird.

## Entscheidung
1. **Neues, eigenständiges Modul `guides`** (importiert **nur** `kernel/*`, `guides.api` leer, kein Modul
   importiert `guides`). import-linter-Contract „guides must not depend on other modules" (17. Contract).
   Spätere `object_links` (Rezept↔Anleitung, Task↔Anleitung) laufen über `guides.api`/Events.
2. **Tabelle `guides`** (Migration 0047, HouseholdScoped-Mixin): `author_id`, `title`, `body_md`,
   `category`, `tags text[]`; RLS `household_isolation` (USING + WITH CHECK) + FORCE + Versions-Trigger
   (ETag). **RLS-Negativtest** (A↛B→0).
3. **Deutsche FTS über eine GENERATED Spalte** `search_tsv tsvector GENERATED ALWAYS AS
   (to_tsvector('german', coalesce(title,'') || ' ' || coalesce(body_md,''))) STORED` + **GIN-Index**.
   Die 2-arg-Form `to_tsvector(regconfig, text)` ist **immutable** (Voraussetzung für GENERATED). Die
   Suche (`list_guides(q=…)`) nutzt `search_tsv @@ plainto_tsquery('german', q)`, sortiert nach
   `ts_rank`. So profitiert die Suche vom **deutschen Stemming** (Query „Fahrrad" trifft „Fahrräder")
   und Stoppwörtern, und der GIN-Index hält sie schnell.
4. **Online-first PATCH + If-Match** (ADR-0029, wie recipes/notes): `version` = ETag, 412 stale /
   428 fehlend; Soft-Delete. Lesen (inkl. Suche) jedes Mitglied; Schreiben member/admin + CSRF.
5. **Events:** `guide.created/updated/deleted` → SSE-Entity `"guides"` (Live-Update der Liste/Suche).

## Konsequenzen
- **Positiv:** echte deutsche Volltextsuche (Stemming/Stoppwörter) ohne Applikationslogik — die DB
  pflegt `search_tsv` automatisch bei jedem Insert/Update; GIN-Index = schnelle Suche; konsistentes
  Modul-Muster; additive Migration; Live-Sync gratis.
- **Abwägung (E9):** **nur** CRUD + FTS + Kategorie/Tags in S6. Die KONZEPT-Punkte **Anhänge**,
  **ACL** (`acl_json` — Sichtbarkeit je Anleitung), **Ansprechpartner** (`contacts`) und `object_links`
  sind bewusst Folge-Slices. `search_tsv` ist als generierte DB-Spalte **nicht** im ORM gemappt (read-
  only); die Query referenziert sie über `literal_column("search_tsv")`.
- **Grenzen:** feste Konfiguration `'german'` (kein per-Haushalt-Sprachumschalter; DE+EN-Mischtexte
  werden mit der deutschen Konfig indexiert — für den DE-first-Haushaltskontext akzeptabel); keine
  Trigram-/Fuzzy-Suche (Tippfehler) in S6.

## Alternativen
- **FTS zur Query-Zeit `to_tsvector(...)` ohne gespeicherte Spalte:** verworfen — kein Index nutzbar
  (Full-Scan + Re-Compute je Query); die GENERATED-Spalte + GIN ist der Standard-Performance-Pfad.
- **`tsvector` per Trigger pflegen** (statt GENERATED): verworfen — GENERATED ist deklarativ, weniger
  Code, kann nicht „vergessen" werden; die immutable 2-arg-Form macht es möglich.
- **App-seitige Suche / `ILIKE '%q%'`:** verworfen — kein Stemming/Ranking, langsam, keine echte FTS;
  KONZEPT verlangt „FTS deutsch".
- **Eigene `search_tsv`-ORM-Spalte schreiben:** verworfen — sie ist DB-generiert; ein App-Write würde
  scheitern; read-only-Referenz genügt.
