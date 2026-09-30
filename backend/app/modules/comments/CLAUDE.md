# CLAUDE.md — Modul `comments`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Generische Kommentare/Threads an beliebigen Objekten (KONZEPT §5.12). P7-S7 = Fundament:
`(object_type, object_id)` + `body_md`. **P7-S18 = Editieren** (PATCH + If-Match, nur Autor).
@-Mentions / Notifications = spätere Slices.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „comments must not depend on
  other modules"). Quermodul nur über Domain-Events (`comment.*`) — `comments.api` ist leer, kein Modul
  importiert `comments`.
- `object_id` ist ein **nacktes UUID, kein FK** — `comments` kennt die kommentierten Module nicht.
- Jede Fachzeile (`comments`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest.

## RLS (Migration 0048, ADR-0065)
- `comments`: `household_id = app.household_id` (USING + WITH CHECK) + FORCE + Versions-Trigger.
- Negativtest: Haushalt A ↛ Haushalt B → 0 Zeilen.

## Schreibpfad
- **PATCH + If-Match** (ADR-0029, online-first): `version` (Mixin, Trigger-bumped) = ETag; 412 stale.
  Der Thread trägt `version` je Eintrag → Inline-Edit **ohne** Einzel-GET. **Kein Sync-Batch.**

## Schnittstellen (HTTP, `/v1/comments`)
- `GET ?object_type=&object_id=` (member, älteste zuerst) · `POST` (member/admin, CSRF, 201, +ETag) ·
  `PATCH {id}` (member/admin, CSRF, If-Match, **nur Autor** → 403, 412 stale) ·
  `DELETE {id}` (member/admin, CSRF, 204, **nur Autor** → 403 sonst).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `comment.created`, `comment.updated`, `comment.deleted` → SSE-Entity `"comments"`.
- **abonniert (via Composition-Root-Handler, P7-S20):** `recipe.deleted`/`note.deleted`/`guide.deleted`
  → `service.purge_for_object` (Reaper: Kommentare des gelöschten Objekts soft-deleten). Handler in
  `handlers.py`, **am Worker-Composition-Root registriert** (`app/worker.py`) — nie im Kernel
  (`kernel ↛ modules`). Event nur **per Name** gematcht (String-Map) → kein Fremdmodul-Import; eigene
  `scoped_session`; idempotent (Re-Run trifft keine lebenden Zeilen).

## No-Gos
- **Keinen** FK auf fremde Tabellen legen (generischer `object_type`/`object_id`-Diskriminator).
- `comments` importiert **kein** anderes Modul; Reaktion nur über `comment.*`-Events.
- Fremde Kommentare nicht löschbar (nur der Autor); Soft-Delete statt Hard-Delete.
