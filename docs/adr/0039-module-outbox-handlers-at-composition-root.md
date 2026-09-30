# ADR-0039: Modul-Outbox-Handler mit Domänen-Seiteneffekt am App-Composition-Root registrieren

- **Status:** beschlossen
- **Datum:** 2026-06-23
- **Betrifft:** `app/worker.py`, `app/modules/capture`, `app/kernel/events`, `app/kernel/sync` · **Bezug:** KONZEPT §5.17, ADR-0032 (Sync-Batch), ADR-0035 (Ledger-Naht)
- **Phase/Slice:** P4-S9b

## Kontext

Der Deo-Fall (KONZEPT §5.17): eine vorgemerkte Folge-Aufgabe ② („Deo in den Rucksack") wird **scharf**,
sobald Posten ① abgehakt wird. Das ist eine **Reaktion über Modulgrenzen** — `shopping` (Abhaken) →
`tasks` (Aufgabe aktivieren) — und stößt auf zwei harte Regeln:

1. **`kernel ↛ modules`** (import-linter): der bestehende Event-Handler `invalidation_bridge` und die
   `registry.py` leben im Kernel; ihr Doc sagt ausdrücklich „Handler leben im Kernel, das Modul *emittiert*
   nur". Ein Handler, der `tasks.api` aufruft, dürfte **nicht** im Kernel liegen.
2. **`shopping ↮ tasks`**: keines darf das andere importieren; der Sync-Batch-Schreibpfad
   (`kernel/sync/apply.py`) ist generisch und darf nicht an Domänenlogik koppeln.

## Entscheidung

1. **Item-granulares Event, additiv & domänen-agnostisch.** `EntitySpec` bekommt ein deklaratives
   `transition_events: {feld -> event_type}`. `apply_batch` emittiert das Event, wenn das Feld auf einer
   Op **falsy → truthy** kippt (Payload `{"id", "user_id"}`). `shopping`'s Spec deklariert
   `{"checked": "shopping.item.checked"}`. Der generische Sync-Engine kennt **keinen** Domänennamen — nur
   die Modul-Spec benennt ihn.
2. **Der reagierende Handler lebt im Modul `capture`** (`capture/handlers.py`,
   `on_shopping_item_checked`) und ruft `tasks.api.activate_on_item_checked` — die einzige erlaubte,
   öffentliche Naht. capture → tasks.api ist bereits zulässig; kein Modul importiert capture (kein Zyklus).
3. **Registrierung am App-Composition-Root, nicht im Kernel.** Der Worker (`app/worker.py`) ist
   app-Ebene und **darf** Module importieren. Beim `WORKER_STARTUP` bindet er die Modul-Handler auf den
   Kernel-Dispatcher (`register_capture_handlers(get_dispatcher())`). Der Kernel
   (`registry.py`/`handlers.py`) bleibt **modulfrei** — `kernel ↛ modules` hält. Kernel-Handler
   (invalidation_bridge) bleiben im Kernel.
4. **Aktivierung serverautoritativ + idempotent.** `tasks.create_armed_task` legt die Folge-Aufgabe als
   `status='armed'` (neuer Status, additiv; aus der Default-Liste ausgeschlossen) mit
   `activation_json={"on_item_checked": "<item_id>"}` an. Der Handler öffnet eine **eigene**
   household-scoped Session (`scoped_session`) und schaltet `armed → open`. Zustellung ist
   at-least-once; eine erneute Zustellung findet keine `armed`-Zeile mehr → No-Op.

## Konsequenzen

- **Positiv:** Erste saubere, zyklusfreie Cross-Modul-**Reaktion** über das Outbox-System; das Muster
  ist wiederverwendbar (z. B. Auto-Settle des Marketplace, ADR-0037, kann später ebenso am
  Composition-Root andocken). `kernel/sync` bleibt domänen-agnostisch; `kernel/events` bleibt modulfrei.
- **Negativ / Kosten:** Die Aktivierung ist **asynchron** (Worker-Latenz ~1 s Poll), nicht im
  Abhak-Request. Bewusst — synchron würde `shopping → tasks` koppeln. Der Worker importiert jetzt
  `capture` (und transitiv `tasks`); das ist erlaubt (Composition-Root) und gewollt.

## Alternativen (verworfen)

- **Handler im Kernel** (`kernel/events/handlers.py`) — verletzt `kernel ↛ modules`, sobald er
  `tasks.api` aufruft. Verworfen.
- **Synchron im Sync-Batch-Schreibpfad** — koppelt den generischen `kernel/sync`-Engine an Domänenlogik
  und erzwänge `shopping → tasks`. Verworfen.
- **`shopping_items.follow_up_json`** (Link auf der shopping-Seite, wie in KONZEPT §10 skizziert) — dann
  müsste der Aktivierungs-Leser shopping-Interna kennen. Stattdessen lebt der Link als `activation_json`
  auf der **tasks**-Seite; shopping bleibt ahnungslos und emittiert nur das item-granulare Event.
