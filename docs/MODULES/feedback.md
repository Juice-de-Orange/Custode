# Modul `feedback`

**Zweck:** In-App-Feedback-Kanal für die Friends&Family-Beta (Roadmap Phase 8, P8-S5). Kategorie
(bug/idea/praise/other) + Freitext, optional ein **Fehler-Referenzcode** (ARCH §12) und die Route.
Mitglieder sehen ihre **eigenen** Einsendungen.

## Datenmodell
| Tabelle | Spalten | RLS |
|---|---|---|
| `feedback` | Standard-Mixin (id uuidv7, household_id, created_at, updated_at, version, deleted_at) + `author_id`, `category` (varchar 20), `message` (text), `error_ref` (varchar 64, nullable), `route` (varchar 120, nullable), `diagnostics` (jsonb, nullable — opt-in Diagnose-Anhang: App-Version + Brotkrumen-Ringpuffer, **keine** Inhalte; Migration 0062) | `household_id = app.household_id` (USING + WITH CHECK) + FORCE + Versions-Trigger |

Migration 0054. RLS-Negativtest (`test_feedback_rls.py`: A↛B→0, WITH CHECK). Index auf
`(author_id, created_at DESC) WHERE deleted_at IS NULL` für die Eigene-Liste.

## Schnittstellen (HTTP, `/v1/feedback`)
- `GET` (member) → `list[FeedbackResponse]` — die eigenen Einsendungen des Aufrufers, neueste zuerst.
- `POST` (member/admin, CSRF, 201) → `FeedbackResponse`. `category` ist ein fixes Set
  (`FeedbackCategory`); unbekannte Werte → 422. `error_ref`/`route`/`diagnostics` optional
  (Diagnose-Anhang: `extra="forbid"` + Längen-Cap → 422 bei Fremdschlüsseln/Überlänge).
- **Cross-Modul:** keins — `feedback.api` ist leer; kein Modul importiert `feedback`. Die
  Betreiber-Konsole (P8-S8) liest später nur eine Aggregat-/Aktions-Sicht, nie diese Fachtabelle.

## Events
- **publiziert:** `feedback.created` (Payload trägt die `id`) → SSE-Entity `"feedback"` (eigene Liste
  live) **und** Auslöser der optionalen Issues-Weiterleitung (ADR-0076).
- **abonniert (Composition-Root-Handler, ADR-0076):** `feedback.created` → `handlers.on_feedback_created`
  lädt die Zeile haushaltsgescopt, `forward.build_issue` bildet sie ab, ein `IssueTrackerPort`
  (Null/GitHub, per `issue_factory` gewählt) leitet **best-effort** weiter — **inert per Default** (kein
  Token → Null-Adapter), bricht nie die Einsendung, loggt nie die `message`.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | fremder Haushalt |
|---|---|---|---|---|
| `GET /feedback` | ✗ (401) | ✗ (403) | ✓ (nur eigene) | RLS: nur eigene |
| `POST /feedback` | ✗ (401) | ✗ (403) | ✓ | **RLS** (WITH CHECK) |

## Tests
- `test_feedback_rls.py` — RLS-Negativ + WITH CHECK für `feedback` (Testcontainers).
- `test_feedback_http.py` — Absenden + Eigene-Liste (neueste zuerst, `error_ref` optional);
  unbekannte Kategorie → 422; ohne Auth → 401/403.
- `test_feedback_forward.py` — Issues-Weiterleitung (ADR-0076), rein (ohne Docker): Null-No-Op +
  Factory-Auswahl (beide Enhancement-Pfade), GitHub-Adapter (wohlgeformter POST + graceful bei
  HTTP-/Netzfehler), `build_issue`-Abbildung, Swallow-All im Handler.

## No-Gos
- **Kein** Inhalt/PII in Logs (`message` wird gespeichert, nie geloggt).
- `feedback` importiert kein anderes Modul; Betreiber-Zugriff später nur über Aggregat/Aktion (ADR-015).
