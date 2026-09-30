# ADR-0068 — Zuruf: optionale LLM-Anreicherung (Ollama) als Graceful Enhancement

**Status:** beschlossen · **Phase:** 7 (P7-S17) · **Datum:** 2026-06-24
**Kontext-KONZEPT:** §5.17 (Zuruf/Quick-Capture), Root-`CLAUDE.md` („Graceful Enhancement … KI sind
optional. Jede Funktion hat einen vollwertigen Basis-Pfad ohne sie (Null-Adapter)" · „LLM: lokal
(Ollama)"), Roadmap Phase 7.

## Kontext
Der Zuruf (`capture`) zerlegt einen Freitext deterministisch in einen Vorschlag (`parse_capture`,
ADR-0038). Das ist robust, offline und vollständig getestet — aber es bleibt eine reine
Regel-Heuristik. Phase 7 sieht eine **optionale LLM-Anreicherung** vor, die mehrdeutige Freitexte
besser normalisiert (Label säubern, Menge/Einheit/Zeit erkennen, Tags ergänzen). Harte Leitplanken:

- **Graceful Enhancement:** Ohne LLM muss alles unverändert funktionieren (Null-Adapter). Ein LLM ist
  ein **Plus**, nie eine Voraussetzung.
- **LLM-Ausgabe schema-validiert, nie direkt persistiert** (Root-`CLAUDE.md`); Vault-Inhalte erreichen
  nie das LLM (hier irrelevant — capture liest keinen Vault).
- **Kein SSRF:** Die LLM-Adresse ist Server-Config, kein Nutzer-Input.
- **Keine Inhalte/PII in Logs.**

## Entscheidung

### Port/Adapter via Composition-Root (wie Mail/Weather)
- `kernel/ports/llm.py` definiert `LlmPort.extract(*, prompt, schema) -> LlmResult` und
  `LlmResult(available: bool, data: dict | None)` (`UNAVAILABLE_LLM = LlmResult(available=False)`).
- **Adapter:** `adapters/ollama/llm.py::OllamaLlm` (POST `/api/generate` an ein **lokales** Ollama mit
  `format=<schema>` für Structured Outputs, `temperature=0`); `adapters/null/NullLlm` gibt immer
  `UNAVAILABLE_LLM`. Auswahl im Composition-Root `app/main.py::_build_llm` über `settings.ollama_*`
  (Default `ollama_enabled=False` → Null). `get_llm(request)` liest `request.app.state.llm`; das Modul
  hängt nur an `kernel/*` — import-linter verbietet `modules/kernel → adapters`.
- **Jeder Fehler** (Server aus, Timeout, kaputtes JSON, kein dict) degradiert zu `UNAVAILABLE_LLM`; der
  Adapter wirft nie in den Request-Pfad. Geloggt wird **nur die Fehlerklasse**, nie Prompt/Antwort.

### Merge: deterministischer Boden, LLM nur als Verfeinerung (`capture/enrich.py`, rein)
`merge_enrichment(base: ParsedProposal, llm: LlmResult) -> ParsedProposal`:
- **Routing bleibt deterministisch:** `target` **und** `follow_up` kommen **immer** aus `base`. Ein LLM
  kann den Zuruf nicht in ein anderes Ziel verschieben oder eine Aktionskette erfinden/löschen.
- **Freitext-Felder** (`label`/`qty`/`unit`/`assignee_hint`/`when`): der LLM-Wert füllt **nur** leere
  Slots — eine zuversichtliche deterministische Extraktion wird nie überschrieben.
- **Tags:** Union (deterministisch zuerst), dedupliziert, Nicht-Strings/Leerstrings ignoriert.
- Das Schema (`ENRICH_SCHEMA`) ist bewusst ein **Subset** von `ParsedProposal` (kein `target`,
  kein `follow_up`). Das Ergebnis wird über `ParsedProposal(...)` (Pydantic) **validiert** — nichts
  Unvalidiertes erreicht je `proposal_json`.

### Aufruf
`capture.service.create_capture` parst zuerst (`base = parse_capture(raw_text)`), ruft dann
`llm.extract(...)` und merged: `proposal = merge_enrichment(base, llm_result)`. Bei Null-Adapter ist
`proposal == base` — identisches Verhalten wie vor diesem Slice.

## Konsequenzen
- **Plus:** Bessere Vorschläge wo ein LLM verfügbar ist, **ohne** jede deterministische Garantie oder
  Testbarkeit aufzugeben. Der Merge ist rein + unit-getestet; das Routing ist beweisbar LLM-unabhängig.
- **Plus:** Krypto-/Anbieter-agnostisch in dem Sinn, dass ein Wechsel des LLM-Backends nur einen neuen
  `LlmPort`-Adapter braucht (kein Modul-Code, keine Migration).
- **Minus:** Ein synchroner LLM-Call im Schreibpfad kostet Latenz, begrenzt durch `ollama_timeout_s`
  (Default 8 s) → bei Timeout deterministischer Vorschlag. (Eine spätere Verschiebung in einen
  Hintergrund-Task/`status='auto'`-Pfad bleibt offen.)
- **Minus:** Die LLM-Qualität ist nicht testbar deterministisch — deshalb ist der LLM **nie** Quelle der
  Wahrheit fürs Routing, nur eine additive Verfeinerung.
- **Offen:** Hintergrund-Anreicherung statt synchron; Confidence-Schwellen; kindgerechter Zuruf.

## Alternativen
- **LLM als Parser-Ersatz:** verwirft die deterministische Robustheit/Offline-Fähigkeit und macht den
  Zuruf vom LLM abhängig — verletzt Graceful Enhancement. Verworfen.
- **LLM darf `target`/`follow_up` setzen:** ein Halluzinat könnte einen Zuruf falsch routen oder eine
  Aktionskette erfinden. Verworfen — Routing bleibt deterministisch.
- **Remote-LLM-API:** Inhalte (potenziell PII) verließen den Server. Verworfen — lokal (Ollama).
