# ADR-0029: Rezepte via PATCH + If-Match (Sync-Batch erst ab Phase 3)

- **Status:** beschlossen
- **Datum:** 2026-06-19
- **Betrifft:** `modules/recipes`, `kernel/http` · **Bezug:** ARCHITECTURE §10 (Sync), §7 (API), Roadmap Phase 2/3

## Kontext

ARCHITECTURE §10 legt den Sync-Batch als **einzigen Schreibpfad für offlinefähige Entitäten** fest
(LWW pro Feldgruppe, Idempotenz via `client_op_id`); ETag/PATCH (§7) gilt nur für **nicht
synchronisierte** Ressourcen. Der Sync-Batch ist bislang **nicht implementiert** (Spezifikation
komplett, Code = 0) und laut Roadmap erst **Phase 3** (Einkaufsliste, der erste Offline-Konsument)
dran. Rezepte sind in Phase 2 **online-first** (Web-Offline für Rezepte ist nicht im Phase-2-Scope;
Android-Caching erst Phase 10). Sie brauchen aber optimistische Nebenläufigkeit gegen
gleichzeitige Edits.

## Entscheidung

**Rezepte nutzen in Phase 2 PATCH + If-Match** (nicht den Sync-Batch). Der ETag ist die
`HouseholdScoped.version`-Spalte (vom gemeinsamen `set_updated_and_version`-Trigger gebumpt); GET/PATCH
tragen `ETag`/`If-Match`, ein stale Wert → **412**, ein fehlender → **428**. Der If-Match-Parser ist
ein **geteiltes Kernel-Utility** (`kernel/http/conditional.py::parse_if_match`), aus dem accounts-
Profil-Pfad (S11) extrahiert und nun von accounts + recipes gemeinsam genutzt. Werden Rezepte später
offline-schreibbar, können sie **additiv** auf den Sync-Batch (ab Phase 3) migrieren.

## Konsequenzen

- **Positiv:** kein verfrühter Sync-Batch-Bau (YAGNI — Phase 2 schreibt nicht offline); konsistent mit
  dem bereits etablierten, getesteten If-Match-Pfad (S11); ein gemeinsamer Parser statt Duplikat.
- **Negativ / Kosten:** zwei Schreibmodelle im System (If-Match jetzt, Sync-Batch ab Phase 3) — bewusst,
  klar getrennt nach „offlinefähig?". Eine spätere Migration der Rezepte auf Sync-Batch ist möglich,
  aber Arbeit (Feldgruppen + Outbox-Client).
- **Auswirkungen:** `kernel/http/conditional.py` (neu, von accounts + recipes genutzt); Rezept-PATCH
  testet 412/428; OpenAPI additiv. Kein Migrations-/RLS-Sonderfall (Standard-HouseholdScoped + Trigger).

## Alternativen (verworfen, mit Begründung)

- **Sync-Batch jetzt bauen** — der „richtige" Endzustand für offlinefähige Entitäten, aber Phase 2
  schreibt Rezepte nicht offline; Bau vor Bedarf (Roadmap setzt ihn auf Phase 3). Verworfen (YAGNI).
- **PUT-Replace ohne If-Match** — einfacher, verliert aber optimistische Nebenläufigkeit (letzter
  Schreiber überschreibt stillschweigend). Verworfen.
- **`_parse_if_match` in recipes duplizieren** — Drift-Gefahr; ein Kernel-Utility ist die saubere
  Wiederverwendung. Verworfen.
