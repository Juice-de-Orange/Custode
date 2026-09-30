# CLAUDE.md — Modul `feedback`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
In-App-Feedback-Kanal für die Friends&Family-Beta (Roadmap Phase 8). P8-S5 = Fundament:
Kategorie (bug/idea/praise/other) + Freitext + optionaler **Fehler-Referenzcode** (ARCH §12) +
Route. Mitglied sieht die **eigenen** Einsendungen. **Opt-in Diagnose-Anhang** (`diagnostics`-JSONB,
Migration 0062): App-Version + gedeckelter Ringpuffer technischer Brotkrumen (Route/Fehlercode/Status),
**nie Inhalte/PII** — `extra="forbid"` + Längen-Cap. Die Betreiber-Konsole liest Einsendungen (P8-S8)
**nur** über die View `ops_feedback` (inkl. `diagnostics`), nie diese Fachtabelle (ADR-015).
**Issues-Weiterleitung ✅ (ADR-0076):** optionale Best-Effort-Weiterleitung an GitHub Issues über einen
`IssueTrackerPort` (Kernel) + Null-/GitHub-Adapter, gewählt in `app/issue_factory` — **inert per
Default** (kein Token → Null-Adapter, kein Aufruf). Auslöser = Outbox-Handler auf `feedback.created`.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul (import-linter: „feedback must not depend on
  other modules"). `feedback.api` ist leer; kein Modul importiert `feedback`.
- Jede Fachzeile (`feedback`) trägt `household_id`; RLS aktiv (`FORCE`), Negativtest
  (`test_feedback_rls.py`). `household_id`/`author_id` kommen aus dem Principal/RLS.

## RLS (Migration 0054)
- `feedback`: `household_id = app.household_id` (USING + WITH CHECK) + FORCE + Versions-Trigger.
- Negativtest je Tabelle: Haushalt A ↛ Haushalt B → 0 Zeilen.

## Schreibpfad
- **Online-first** (kein Sync-Batch): `POST` legt an, `GET` listet die eigenen Einsendungen.
  Keine Edit-/Delete-Endpunkte in v1 (Einsendungen sind unveränderlich aus Nutzersicht).

## Schnittstellen (HTTP, `/v1/feedback`)
- `GET` (member; eigene Einsendungen, neueste zuerst) ·
  `POST` (member/admin, CSRF, 201; 422 bei unbekannter Kategorie).
- **Services (`api.py`):** leer.

## Events
- **publiziert:** `feedback.created` (Payload trägt jetzt die `id`) → SSE-Entity `"feedback"` (eigene
  Liste live) **und** Auslöser der Issue-Weiterleitung.
- **abonniert (via Composition-Root-Handler, ADR-0076):** `feedback.created` → `handlers.on_feedback_created`
  lädt die Zeile haushaltsgescopt, bildet sie via `forward.build_issue` ab und übergibt sie dem
  `IssueTrackerPort`. Handler in `handlers.py`, **am Worker-Composition-Root registriert** (`app/worker.py`)
  mit dem per Factory gewählten Tracker — nie im Kernel (`kernel ↛ modules`, `modules ↛ adapters`).
  Best-effort: bricht nie die Einsendung; nur Fehlerklasse geloggt, nie die `message` (kein PII).

## No-Gos
- **Kein** PII/Inhalt in Logs — die `message` wird gespeichert, nie geloggt (Root-CLAUDE.md).
- `feedback` importiert **kein** anderes Modul; kein Modul importiert `feedback`.
- Betreiber-Zugriff später nur über Aggregat/Aktion (ADR-015), nie direkt auf `feedback`.
