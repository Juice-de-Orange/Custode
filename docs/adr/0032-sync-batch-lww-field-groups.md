# ADR-0032: Sync-Batch — LWW pro Feldgruppe (Offline-Schreibpfad)

- **Status:** beschlossen
- **Datum:** 2026-06-20
- **Betrifft:** `kernel/sync`, `modules/shopping` · **Bezug:** ARCHITECTURE §10 (Sync), ADR-003, KONZEPT §7.3

## Kontext

Die Einkaufsliste (Phase 3) ist die **erste offlinefähige** Entität. ARCHITECTURE §10 legt fest:
„Sync-Batch ist der einzige Schreibpfad für offlinefähige Entitäten" — Geräte editieren offline und
pushen später; konkurrierende Edits dürfen **nicht verloren** gehen. Klassisches Beispiel: Gerät A
hakt einen Posten ab (`checked`), Gerät B benennt ihn um (`label`) — beide offline. Eine
ganze-Zeile-„Last-Write-Wins"-Strategie würde eine Änderung verwerfen. CRDTs lösen das, sind aber
operativ schwer. ADR-003 entschied bereits **LWW pro Feldgruppe statt CRDT**; dieses ADR konkretisiert
die Umsetzung.

## Entscheidung

**Der Sync-Batch wendet LWW pro Feldgruppe an, umgesetzt als Feld-Merge:**

- **`POST /v1/sync/{module}/batch`** nimmt Ops `[{client_op_id, entity, id, base_version, op, fields}]`.
  Ein Op trägt **nur die geänderten Felder**; der Server schreibt nur diese (Feld-Merge). Damit gewinnt
  pro Feld der zuletzt empfangene Op — **unabhängige Felder kollidieren nie**.
- **Feldgruppen** (Doku + Validierung): `shopping_item` Gruppe A = {label, qty, unit, category},
  Gruppe B = {checked}. „Abhaken" sendet nur Gruppe B, „Umbenennen" nur Gruppe A → garantiert
  konfliktfrei. Die Gruppen-Granularität ergibt sich aus „nur vorhandene Felder schreiben".
- **Server-Empfangszeit** = Verarbeitungsreihenfolge entscheidet (Client-Uhren werden nie geglaubt).
- **Idempotenz:** `client_op_id` → Tabelle `sync_client_ops` (`(household_id, client_op_id)` unique);
  Replay = No-Op (Insert ON CONFLICT, dann Apply nur bei frischem Claim).
- **`base_version`** ist **informativ** — der Sync-Batch **rejectet nicht** (kein optimistisches Lock;
  LWW löst Konflikte, statt sie abzulehnen).
- **Deletes sind sticky:** einmal `deleted_at` gesetzt, hebt ein späterer Edit es nicht auf →
  deterministische Konvergenz unabhängig von der Reihenfolge.
- **Generisch** in `kernel/sync` (`apply_batch`, `ModuleSpec`); ein Modul deklariert nur seine
  Entities + Felder (`shopping/spec.py`). Server-Autorität-Felder (`checked_by`/`reserved_by`/
  `created_by`) sind **nicht** client-schreibbar.

## Konsequenzen

- **Positiv:** einfach + deterministisch (kein CRDT-Op-Tree); konfliktarm (per-Feld-Merge); ein
  Algorithmus für alle künftigen Offline-Module (Mealplan, Tasks). Die §10-Pflicht-Property-Matrix
  (gleiches/verschiedenes Feld, delete+edit, Replay, Resync) sichert „kein bestätigter Op geht verloren".
- **Kosten:** **zwei Schreibmodelle** im System — Sync-Batch (offlinefähig) vs. PATCH+If-Match
  (Settings/Admin, ADR-0029). Bewusst getrennt nach „offlinefähig?". LWW kann ein Feld eines
  langsamen Geräts überschreiben (gewollt: letzter gewinnt; keine stille Merge-Magie).

## Alternativen (verworfen)

- **CRDT** — verlustfrei auch bei beliebiger Nebenläufigkeit, aber operativ komplex (Op-/State-Trees,
  GC). Für Haushalts-Listen Overkill. Verworfen (ADR-003).
- **Optimistisches Lock (If-Match, 412 reject)** — würde Offline-Edits verwerfen → Datenverlust beim
  Sync. Verworfen für offlinefähige Typen.
- **Ganze-Zeile-LWW** — „Abhaken" würde gleichzeitiges „Umbenennen" überschreiben (genau der Konflikt,
  den die Feldgruppen vermeiden). Verworfen.
