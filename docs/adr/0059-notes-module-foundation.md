# ADR-0059 — `notes`-Modul: manuelles Fundament (online-first, PATCH + If-Match)

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 7 / P7-S1
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Phase 7 bringt Notizen (KONZEPT §5: Notizen mit Markdown, Dashboard-Pin, „Konvertieren-zu",
5-Versionen-Historie). Wie bei `recipes`/`mealplanner` wird zuerst das **manuelle Fundament** gebaut;
Historie/Konvertieren/Dashboard-Pin-Sicht folgen in späteren Slices. Zu entscheiden: Datenmodell,
Schreibpfad, Modulgrenzen.

## Entscheidung
1. **Neues, eigenständiges Modul `notes`** (importiert **nur** `kernel/*`, nie ein anderes Feature-
   Modul; `notes.api` ist leer). import-linter-Contract „notes must not depend on other modules"
   (15. Contract). Quermodul-Reaktion (später „Brief → Notiz") läuft über die **`note.*`-Events**, nicht
   synchron — kein Modul importiert `notes`.
2. **Tabelle `notes`** (Migration 0044, HouseholdScoped-Mixin wie alle Fachtabellen): `author_id`,
   `title`, `body_md` (Markdown-Text), `pinned` (bool). RLS `household_isolation` (USING + WITH CHECK)
   + FORCE + gemeinsamer `set_updated_and_version`-Trigger (`version` = ETag). **RLS-Negativtest**
   (A↛B→0, WITH-CHECK-Verstoß → InsufficientPrivilege). Partial-Index auf `pinned WHERE NOT deleted`
   für die spätere Dashboard-Pin-Sicht.
3. **Online-first: PATCH + If-Match** (ADR-0029, wie `recipes`/`tasks`): `version` ist der ETag; 412
   bei stale, 428 bei fehlend (`kernel/http/conditional.py`). **Kein Sync-Batch** — Notizen sind
   online-first (Offline-Dexie kann später folgen, wie bei der Einkaufsliste). Soft-Delete (Historie
   bleibt für die spätere Versions-/Wiederherstellungs-Funktion).
4. **AuthZ:** Lesen = jedes Haushaltsmitglied; Schreiben (POST/PATCH/DELETE) = member/admin mit CSRF.
   `author_id` aus dem Principal. (Kinder-Notizen/ACL pro Notiz = spätere Verfeinerung.)
5. **Events:** `note.created`/`updated`/`deleted` (transactional outbox) → SSE-Entity `"notes"`
   (`handlers.py`) für Live-Update auf anderen Geräten.

## Konsequenzen
- **Positiv:** konsistent mit dem etablierten Modul-Muster (recipes/mealplanner) → wenig Neues;
  einseitige Modulgrenze; additive Migration; Live-Sync gratis über das Event-Registry; das Fundament
  trägt die späteren Slices (Historie/Konvertieren/Pin-Sicht/object_links).
- **Abwägung (E9):** **Nur** das manuelle CRUD + Pin in S1 — die KONZEPT-Punkte „5 Versionen",
  „Konvertieren-zu" (Notiz↔Task/Rezept/…), Dashboard-Pin-**Sicht** und Kommentare/@-Mentions sind
  bewusst Folge-Slices. Klar dokumentiert (wie P6-S1 beim Mealplanner).
- **Grenzen:** keine Versions-Historie in S1 (Soft-Delete + `version`-Spalte legen die Basis); keine
  Offline-Bearbeitung (online-first); kein Reicht-Editor (Markdown-Rohtext, Rendering = Folge-Slice).

## Alternativen
- **Notizen in einem bestehenden Modul** (z. B. `recipes`): verworfen — Notizen sind ein eigener
  Querschnitts-Inhaltstyp (KONZEPT §5), mit eigenen Events/Verknüpfungen; ein eigenes Modul hält die
  Grenzen sauber.
- **Sync-Batch wie die Einkaufsliste:** verworfen für S1 — Notizen brauchen kein Offline-Mehrgeräte-
  Merge als Erstes; online-first + If-Match ist einfacher und serverautoritativ. Offline kann später
  additiv dazukommen.
- **Versions-Historie sofort** (eigene `note_versions`-Tabelle): verschoben — eigener Slice; die
  `version`-Spalte + Soft-Delete sind die Naht, an der sie andockt.
