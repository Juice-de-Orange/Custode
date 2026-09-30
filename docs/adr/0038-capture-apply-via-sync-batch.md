# ADR-0038: Capture — Vorschläge serverseitig über die Ziel-Modul-APIs anwenden (shopping via Sync-Batch)

- **Status:** beschlossen
- **Datum:** 2026-06-23
- **Betrifft:** `modules/capture` (neu), `modules/shopping`, `modules/tasks` · **Bezug:** KONZEPT §5.17, ADR-0032 (Sync-Batch), ADR-0034 (tasks)
- **Phase/Slice:** P4-S9a

## Kontext

KONZEPT §5.17: der **Zuruf** ist das universelle Freitext-Eingangstor. Der offline Regel-Parser
(Stufe 1, ohne LLM) zerlegt einen Freitext in einen Vorschlag (Posten / Task / Unsortiert), der als
``capture`` in der Inbox landet; per 1-Tap-Triage wird er **bestätigt** (legt das Artefakt an) oder
verworfen.

Beim Bestätigen muss `capture` einen **Einkaufsposten** anlegen. Das wirft eine Architektur-Frage
auf: `shopping` ist **offline-first** und sein **einziger** dokumentierter Schreibpfad ist der
**Sync-Batch** (ADR-0032; das Modul-No-Go verbietet andere Pfade ausdrücklich). Ein direkter
Server-Insert wäre ein zweiter Schreibpfad. Ein Task hingegen ist online-first (PATCH/POST,
ADR-0034) und serverautoritativ anlegbar.

## Entscheidung

1. **Confirm wendet den Vorschlag serverseitig über die öffentlichen Ziel-Modul-APIs an** — synchron,
   in derselben Transaktion wie der Statuswechsel der Capture:
   - **Posten:** `capture.service` ruft `shopping.api.apply_shopping_batch(...)` mit **einer
     synthetischen Upsert-Op** auf. Das nutzt den **bestehenden** Sync-Batch-Pfad — **kein zweiter
     Schreibpfad**, das `shopping`-No-Go bleibt gewahrt. Die `client_op_id` ist **deterministisch**
     aus der capture-id abgeleitet (`uuid5`), daher ist ein wiederholtes Confirm **idempotent**
     (kein Doppelposten; der 409-Wächter „nicht mehr proposed" greift ohnehin zuerst).
   - **Task:** `capture.service` ruft `tasks.api.create_personal_task(...)` (punktelos, §5.6/5.9) —
     eine neue, primitiv-argumentierte öffentliche Funktion, damit `capture` **keine** tasks-Schemas
     importieren muss.
   - **Note / Unsortiert:** in S9a **nicht** anlegbar (kein notes-Modul vor Phase 7, kein Ziel) → 409;
     die Capture bleibt zur manuellen Zuordnung in der Inbox.
2. **Default-Liste:** `shopping.api.ensure_default_list(...)` (additiv) liefert die zuletzt
   aktualisierte Liste oder legt — **ebenfalls über den Sync-Batch** (deterministische `client_op_id`)
   — eine technische Default-Liste an (generischer Name „Einkauf", **kein** Marketingname). Der Client
   zieht beides beim nächsten Delta-Pull.
3. **Einseitige Abhängigkeit `capture → {shopping.api, tasks.api}`.** Kein Modul importiert capture
   ⇒ kein Zyklus (import-linter erzwingt es, 2 neue Contracts).

## Konsequenzen

- **Positiv:** `confirm` ist atomar + idempotent + serverautoritativ; das `shopping`-No-Go bleibt
  unverletzt (ein einziger Schreibpfad). Voll serverseitig testbar (HTTP-Test prüft den erzeugten
  Posten via Delta-Pull). Saubere, zyklusfreie Modulgrenzen.
- **Negativ / Kosten:** Ein server-originierter Posten umgeht die client-seitige Dexie-Optimistik —
  er erscheint erst nach dem nächsten Pull/SSE-Refresh. Akzeptabel: das SSE-`capture`-Hint + die
  `shopping`-Invalidierung der Confirm-Mutation lösen den Refresh sofort aus.

## Alternativen (verworfen)

- **Neuer direkter `shopping.add_item`-Schreibpfad** — einfachster Code, aber widerspricht dem
  `shopping`-No-Go (Sync-Batch ist der einzige Schreibpfad). Verworfen.
- **Client wendet an** (Server speichert nur den Vorschlag; der Web-Client legt den Posten über seine
  Offline-Pipeline an) — strikt offline-treu, aber verteilt die Apply-Logik/Tests auf den Client und
  macht den Server-`confirm` zu einem reinen Marker. Verworfen zugunsten eines atomaren,
  serverseitig testbaren Pfads.
