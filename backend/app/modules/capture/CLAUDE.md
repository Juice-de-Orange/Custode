# CLAUDE.md — Modul `capture`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Quick-Capture „Zuruf" (KONZEPT §5.17), der **offline Basispfad ohne LLM**: ein Freitext wird vom
deterministischen Regel-Parser in einen Vorschlag zerlegt und landet als ``capture`` in der Inbox;
per 1-Tap-Triage wird er bestätigt (legt Posten/Task an) oder verworfen. P4-S9a = Parser +
Inbox-Triage. Aktionsketten/Routinen/Deo-Fall-E2E = S9b. **Optionale LLM-Anreicherung (Ollama,
Graceful Enhancement) = P7-S17** (ADR-0068): rein additiv über `enrich.py` — der Parser bleibt der
Basis-Pfad und die Quelle der Wahrheit fürs Routing.

## Grenzen (hart)
- Importiert **nur** `kernel/*` + die **öffentliche** `shopping.api` (Posten über den Sync-Batch) und
  `tasks.api` (persönlichen Task anlegen) — **nie** deren Interna, nie ein anderes Modul. **Kein Modul
  importiert capture** (einseitige Abhängigkeit `capture → shopping/tasks` → **kein Zyklus**;
  import-linter).
- `captures` trägt `household_id`; RLS aktiv (`FORCE`), Negativtest. Inbox ist **per-Mitglied**.

## Datenmodell (Migration 0030)
- `captures`: `member_id`, `raw_text`, `tags text[]`, `status ∈ {proposed,confirmed,dismissed,auto}`
  (CHECK; `auto` reserviert für den späteren Still-Ausführen-Pfad), `proposal_json jsonb` (Parser-
  Ergebnis) (+ Standard-Mixin).

## Parser (`parser.py`, rein, ohne DB/LLM)
- Kauf-Verben → shopping; `#liste`/`#task`/`#notiz` erzwingen das Ziel; Menge+Einheit aus dem Label
  gelöst; `@Name` → assignee_hint; `#tags` + `für …`-Kontext → tags; Zeit-Tags → when; sonst
  „Unsortiert" (`target=none`). **Deterministisch** + voll unit-getestet (läuft ohne Docker).

## Confirm = serverseitig über Ziel-Modul-APIs (ADR-0038)
- **shopping:** `ensure_default_list` + `apply_shopping_batch` mit synthetischer Op + **deterministischer
  `client_op_id`** (aus capture-id) → bestehender Sync-Batch-Pfad, **idempotent**, `source="zuruf"`.
- **task:** `tasks.api.create_personal_task` (punktelos).
- **note/none:** kein Ziel in S9a → 409; Capture bleibt in der Inbox.

## Schnittstellen (HTTP)
- `/v1/capture`: `POST` (Zuruf) · `GET /inbox` · `POST /{id}/confirm` · `POST /{id}/dismiss`. Alle
  **member/admin** (Kinder ✗ in S9a), CSRF auf Writes.

## Aktionsketten (P4-S9b, Deo-Fall, ADR-0039)
- Parser erkennt eine Folge-Klausel (`…, dann <task>`) → `proposal.follow_up`. Confirm legt bei einem
  shopping-Ziel **zusätzlich** eine vorgemerkte Aufgabe an: `tasks.api.create_armed_task(...,
  on_item_checked=<item_id>)` (`status='armed'`, `activation_json`).
- **Handler** (`handlers.py::on_shopping_item_checked`): reagiert auf das item-granulare
  `shopping.item.checked` und ruft `tasks.api.activate_on_item_checked` (`armed → open`). Lebt im Modul,
  **registriert am App-Composition-Root** (`app/worker.py`) — **nie** im Kernel (`kernel ↛ modules`).
  Öffnet eine eigene `scoped_session`; idempotent (at-least-once-tolerant).

## LLM-Anreicherung (P7-S17, ADR-0068, Graceful Enhancement)
- **Nur** `kernel/ports/llm.py::LlmPort` (via `get_llm` → `app.state.llm`, am Composition-Root gewählt:
  `OllamaLlm` wenn aktiviert, sonst `NullLlm`). **Nie** ein Adapter direkt importieren (import-linter:
  `modules/kernel ↛ adapters`).
- `enrich.py` ist **rein** (kein DB/HTTP): `merge_enrichment` legt einen deterministischen Boden —
  `target`/`follow_up` kommen **immer** aus dem Parser, der LLM füllt nur leere Freitext-Slots und
  ergänzt Tags. LLM-Schema = Subset von `ParsedProposal`; Ergebnis Pydantic-validiert.
- **Nie** Prompt/Antwort loggen (PII). **Nie** LLM-Ausgabe ungeprüft persistieren. **Nie** den LLM
  fürs Routing entscheiden lassen. Jeder LLM-Fehler → `UNAVAILABLE_LLM` → Parser-Ergebnis unverändert.

## Events
- **publiziert:** `capture.created`, `capture.processed` → SSE-Entity `"capture"`.
  **abonniert (via Composition-Root-Handler):** `shopping.item.checked` → Folge-Aufgabe aktivieren.

## No-Gos
- **Nie** einen Posten direkt in `shopping_*` schreiben — immer über `shopping.api` (Sync-Batch).
- **Nie** die shopping-/tasks-Tabellen oder -Schemas direkt lesen/importieren (nur via deren `api.py`).
- **Nie** accounts lesen, um `@Name` aufzulösen — der Parser liefert nur einen String-Hint.
- **Den Handler nie im Kernel registrieren** — Modul-Handler binden am Composition-Root (Worker).
- Kinder nicht zurufen lassen (S9a; kindgerechter Zuruf = spätere Erweiterung).
