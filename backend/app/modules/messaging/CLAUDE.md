# CLAUDE.md — Modul `messaging`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Ruhige, asynchrone **Briefe** an den Haushalt (KONZEPT §5.12). P7-S4 = Fundament: Betreff +
Markdown-Body, Rundbrief (leeres `to_ids`) oder adressiert, mit Gelesen-Status. Notifications/Kommentare
= spätere Slices.

## Grenzen (hart)
- Importiert **nur** `kernel/*` + `tasks.api` („Kümmerst du dich?"→Aufgabe, P7-S5, ADR-0063) — nie
  deren Interna oder ein anderes Modul (import-linter: „messaging uses only tasks public api").
  Quermodul sonst nur über Domain-Events (`letter.*`) — `messaging.api` ist leer, kein Modul importiert
  `messaging`.
- Jede Fachzeile (`letters`, `letter_reads`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest je
  Tabelle. `household_id`/`from_id`/`user_id` kommen aus dem Principal/RLS, nie aus einem Cross-Modul-Import.

## RLS (Migration 0046, ADR-0062)
- `letters`: `household_id = app.household_id` (USING + WITH CHECK) + FORCE + Versions-Trigger.
- `letter_reads`: household-scoped, RLS USING+WITH CHECK + FORCE, **append-only** (kein Mixin), unique
  `(letter_id, user_id)`.
- Negativtest je Tabelle: Haushalt A ↛ Haushalt B → 0 Zeilen.

## Gelesen-Status (ADR-0062)
- Eigene Tabelle `letter_reads` statt `read_map_json` (concurrency-sicher: `INSERT … ON CONFLICT DO
  NOTHING`). `GET /{id}` markiert nur für **Empfänger** (Rundbrief/`to_ids`), nie für den Absender.

## Schnittstellen (HTTP, `/v1/letters`)
- `GET` (member) · `GET /unread-count` (member) · `POST` (member/admin, CSRF, 201) · `GET {id}` (member,
  markiert gelesen) · `POST {id}/to-task` (member/admin, CSRF, 201; „Kümmerst du dich?", non-destruktiv).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `letter.created`, `letter.read` → SSE-Entity `"letters"` (`handlers.py`).
- **abonniert:** — (Notification-Fan-out später).

## No-Gos
- Kein `read_map_json`-Read-Modify-Write (Lost-Update); Gelesen-Status nur über `letter_reads`.
- `messaging` importiert **kein** anderes Modul; Reaktion nur über `letter.*`-Events.
- Read-Zeile nur für echte Empfänger schreiben (nicht für den Absender).
