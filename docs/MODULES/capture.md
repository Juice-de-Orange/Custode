# Modul `capture`

**Status:** in Arbeit · **Phase:** 4 · **KONZEPT:** §5.17

## Zweck & Verantwortung
Quick-Capture „Zuruf" (KONZEPT §5.17) — das universelle Freitext-Eingangstor, **offline & ohne LLM**
(Pipeline-Stufe 1, Leitplanke 7). Ein Freitext wird vom deterministischen Regel-Parser in einen
Vorschlag zerlegt und landet als ``capture`` in der Inbox; per 1-Tap-Triage wird er **bestätigt**
(legt Posten/Task an) oder **verworfen**. P4-S9a = Parser + Inbox-Triage; Aktionsketten (Posten→Task
via ``shopping.item.checked``), Routinen, Deo-Fall E2E = **S9b**; **optionale LLM-Anreicherung
(Ollama, Graceful Enhancement) = P7-S17** (ADR-0068).

## Datenobjekte (Migration 0030)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `captures` | id; `member_id`; `raw_text`; `tags text[]`; **Statusmaschine** `status ∈ {proposed,confirmed,dismissed,auto}` (`auto` reserviert für den späteren Still-Ausführen-Pfad); `proposal_json jsonb` (Parser-Ergebnis) | `household_id = app.household_id` (USING + WITH CHECK) |

RLS-Negativtest (`test_capture_rls.py`: A↛B → 0; WITH CHECK).

## Offline Regel-Parser (`parser.py`, rein)
`parse_capture(raw_text) -> ParsedProposal` — deterministisch, ohne DB/LLM:
- **Kauf-Verben** (DE: besorgen/kaufen/holen/brauchen/mitbringen, EN: buy/get/grab/need) → `shopping`.
- **Hint-Tags erzwingen** das Ziel: `#liste`→shopping, `#task`→task, `#notiz`→note.
- **Menge + Einheit** (führende Zahl + Einheit) werden aus dem Label gelöst.
- **`@Name`** → `assignee_hint` (reiner String; capture liest **nicht** accounts).
- **`#tags`** + eine **`für …`/`for …`-Kontextphrase** → `tags`; Zeit-Tags → `when`.
- **Fallback** (kein Verb, kein Hint) → `target=none` („Unsortiert", manuelle Triage).

## Optionale LLM-Anreicherung (`enrich.py`, rein · ADR-0068, Graceful Enhancement)
- **Port/Adapter via Composition-Root:** `LlmPort` (`kernel/ports/llm.py`); `OllamaLlm` (lokal, kein
  SSRF) wenn `settings.ollama_enabled`, sonst `NullLlm` (immer `UNAVAILABLE_LLM`). Default **aus** →
  identisches Verhalten wie ohne LLM. Jeder LLM-Fehler degradiert (nie in den Request-Pfad geworfen);
  geloggt wird nur die Fehlerklasse, **nie** Prompt/Antwort (PII).
- **`merge_enrichment(base, llm)`** (rein, unit-getestet): **Routing bleibt deterministisch** —
  `target` **und** `follow_up` kommen immer aus `base`. Der LLM füllt nur **leere** Freitext-Slots
  (`label`/`qty`/`unit`/`assignee_hint`/`when`) und **ergänzt** Tags (Union, dedupliziert). Das
  LLM-Schema ist ein Subset von `ParsedProposal`; das Ergebnis wird über Pydantic **validiert**
  (nichts Unvalidiertes erreicht je `proposal_json`).

## Confirm = serverseitig über Ziel-Modul-APIs (ADR-0038)
- **shopping:** `shopping.api.ensure_default_list` + `shopping.api.apply_shopping_batch` mit **einer**
  synthetischen Upsert-Op und **deterministischer** `client_op_id` (aus der capture-id) → bestehender
  Sync-Batch-Pfad, **idempotent**, `source="zuruf"`.
- **task:** `tasks.api.create_personal_task` (punktelos, §5.6/5.9).
- **note/none:** kein Ziel in S9a → 409; die Capture bleibt in der Inbox.

## Schnittstellen
- **HTTP `/v1/capture` (member/admin, Kinder ✗):** `POST` (Zuruf → proposed) · `GET /inbox`
  (eigene offene) · `POST /{id}/confirm` · `POST /{id}/dismiss`. CSRF auf Writes.
- **Cross-Modul:** nutzt **nur** `shopping.api` (Posten über Sync-Batch) + `tasks.api` (Task anlegen).
  `capture.api` ist leer (kein Modul importiert capture → kein Zyklus).
- **Events out:** `capture.created`, `capture.processed` → SSE-Entity `"capture"`.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | child | fremder Haushalt |
|---|---|---|---|---|---|
| `POST /capture`, `GET /inbox` | ✗ (401) | ✗ (403) | ✓ | **✗ (403)** | RLS: nur eigene |
| `POST /{id}/confirm`, `/{id}/dismiss` | ✗ | ✗ (403) | ✓ | **✗ (403)** | **404/RLS** |

## Invarianten
- Posten **nur** über den Sync-Batch (kein zweiter `shopping`-Schreibpfad, ADR-0032/0038); Confirm
  **idempotent** (deterministische `client_op_id` + 409-Wächter).
- `capture` liest/schreibt **nie** fremde Tabellen direkt (nur via `*.api`); kein Modul importiert
  capture (import-linter).
- Inbox ist **per-Mitglied** (man sieht nur die eigenen Captures).

## Tests
- `test_capture_parser.py` — Parser-Unit-Tests (kein Docker): Kauf-Verb→shopping + sauberes Label,
  Menge/Einheit, `#task`/`#liste`, `@Name`, `#tags`, Zeit-Tag, Fallback→unsortiert, **Deo-Referenzfall**
  („… Deo für die Arbeit besorgen" → label „Deo" + tag „arbeit"), EN-Kauf-Verb.
- `test_capture_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers).
- `test_capture_http.py` — Zuruf→proposed; confirm `shopping` legt Posten an (Delta-Pull,
  `source=zuruf`); confirm `task` legt persönlichen Task an; confirm idempotent (Re-Confirm 409, kein
  Doppelposten); `none` 409; dismiss; fremder Capture 404; Kind 403.
- `test_capture_enrich.py` — **reine Merge-Tests** (kein Docker): `UNAVAILABLE_LLM`/Nicht-dict → no-op;
  LLM füllt nur leere Slots; `target`/`follow_up` immer aus `base`; Tags-Union dedupliziert;
  Leerstrings ignoriert.

## Aktionsketten (P4-S9b, Deo-Fall E2E, ADR-0039)
- Parser erkennt `…, dann <task>` → `proposal.follow_up`. **Confirm** legt bei shopping-Ziel
  zusätzlich eine **vorgemerkte** Aufgabe an (`tasks.api.create_armed_task`, `status='armed'`,
  `activation_json={"on_item_checked": "<item_id>"}`).
- **Abhaken → Aktivieren:** der Sync-Batch emittiert item-granular `shopping.item.checked`
  (`EntitySpec.transition_events`, falsy→truthy); der **am Worker-Composition-Root registrierte**
  capture-Handler ruft `tasks.api.activate_on_item_checked` (`armed → open`). Asynchron (Outbox),
  idempotent, zyklusfrei (`shopping ↮ tasks`, `kernel ↛ modules`).

## Offene Punkte (S9c / später)
- **Routinen** (`routines`) + Scheduling-Hinweis (`before_routine:<id>`) — die „richtige Zeit".
- **Note**-Ziel (braucht notes-Modul, Phase 7) + Cmd+K-Palette.
- **LLM-Anreicherung im Hintergrund** statt synchron im Schreibpfad (`status='auto'`-Pfad);
  Confidence-Schwellen; kindgerechter Zuruf (ADR-0068 offene Punkte).
