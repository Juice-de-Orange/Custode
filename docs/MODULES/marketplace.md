# Modul `marketplace`

**Status:** in Arbeit · **Phase:** 4 · **KONZEPT:** §5.10

## Zweck & Verantwortung
Handelbare Haushaltsaufgaben mit Escrow (KONZEPT §5.10): ein Mitglied verkauft eine ihm zugewiesene,
offene Task-Instanz zu einem Preis; der Käufer übernimmt sie und erhält bei Erledigung den Escrow.
P4-S8a = Listing/Escrow + Statusmaschine; P4-S8b = Auto-Übernahme + Fairness-Tiebreaker;
Verfall→Rückfall-Cron + Auto-Settle (Worker) = späterer Slice.

## Datenobjekte (Migrationen 0028 + 0029)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `market_listings` | id; `task_instance_id` (reine ID, **kein** Cross-Modul-FK); `title` (Snapshot); `seller_id`; `price>0` (CHECK); **Statusmaschine** `status ∈ {open,accepted,settled,reverted,withdrawn}`; `buyer_id?` | `household_id = app.household_id` (USING + WITH CHECK) |
| `auto_accept_rules` (0029) | id; `member_id`; `template_id?` (NULL = jede Aufgabe); `max_price>0` (CHECK); `active` | `household_id = app.household_id` (USING + WITH CHECK) |

RLS-Negativtest (`test_marketplace_rls.py`: A↛B → 0; WITH CHECK).

## Auto-Übernahme (P4-S8b, Audit A-05)
Ein Mitglied pflegt stehende Regeln „`template_id` (oder jede) bis `max_price` automatisch übernehmen".
Beim Anlegen eines Listings — und beim Anlegen einer Regel — sucht `_try_auto_accept` passende,
**aktive** Regeln anderer Mitglieder (`max_price ≥ price`, Template matcht oder ist NULL; der Verkäufer
ist nie Kandidat). Bei mehreren Kandidaten entscheidet `economy.api.fairness_load` (geringste Last
zuerst, deterministischer Tiebreak per `user_id`); der Gewinner erhält das Listing via `accept_listing`
in **derselben Tx** (kein Worker).

## Escrow (über das economy-Ledger, ADR-0035/0037)
- **Listing:** `member:seller → escrow:<listing_id>` (Preis reservieren; Deckungsprüfung → kein
  negativer Saldo, kein Doppel-Listing).
- **Annehmen:** `tasks.api.reassign_instance` weist die Task dem Käufer zu; Escrow bleibt gesperrt.
- **Settle (Task `done`):** `escrow → member:buyer` (Käufer behält zusätzlich die Basis-Punkte, A-04).
- **Rückzug (offen):** `escrow → member:seller`. **Rückabwicklung** (`accepted→reverted`) seit
  11-S1b: `revert_listing` bucht `escrow → member:seller` und gibt ihm die Aufgabe zurück. Anlass
  ist der Austritt des Käufers — ein zeitlicher Verfall per Cron ist weiterhin nicht gebaut.
  **Rückabwicklung heißt „nicht geliefert" (2026-08-03, BUGLOG).** Ist die Instanz `done`, wird
  **abgerechnet** statt rückabgewickelt: wer die Arbeit gemacht hat, hat verdient — auch wenn er
  gerade austritt (sein Saldo verfällt danach als eigene Buchung). `revert_listing` lehnt eine
  erledigte Instanz mit 409 `task_already_done` ab; eine **getombstonete** Instanz toleriert es,
  denn zurückzugeben ist nichts, aber das Escrow darf nicht auf einem Konto liegen bleiben, das
  keine Route mehr auflöst. Vorher scheiterte hier der ganze Austritt (bei der Auflösung der
  **aller** Mitglieder — eine Transaktion).

## Schnittstellen
- **HTTP `/v1/marketplace/listings` (member/admin, Kinder ✗):** `GET ?status=` (default open) ·
  `POST` (anlegen) · `POST {id}/accept` · `POST {id}/withdraw` · `POST {id}/settle`. CSRF auf Writes.
- **HTTP `/v1/marketplace/auto-accept` (member/admin, Kinder ✗):** `GET` (eigene Regeln) · `POST`
  (Regel anlegen) · `DELETE {rule_id}` (eigene Regel soft-delete). CSRF auf Writes.
- **Cross-Modul:** nutzt **nur** `tasks.api` (get/reassign instance, `instance_status`) +
  `economy.api` (transfer/escrow). `marketplace.api` exportiert `release_positions_of` für den
  Austritt (11-S1b) — kein Modul importiert marketplace → kein Zyklus.
- **Events out:** `market.listing.created`, `market.listing.sold`, `market.trade.settled`,
  `market.trade.reverted` (11-B4) und `market.changed` (Rückzug) → SSE-Entity `"marketplace"`.
  Die vier erstgenannten sind genau die aus KONZEPT §5.10; `market.trade.reverted` war bis 11-B4
  nur ein Name im Konzept. **Ein Typ ohne Eintrag in `_ENTITY_BY_TYPE` verpufft stumm** —
  `tests/test_event_catalogue.py` hält beide Richtungen.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | child | fremder Haushalt |
|---|---|---|---|---|---|
| `GET /listings` | ✗ (401) | ✗ (403) | ✓ | **✗ (403)** | RLS: nur eigene |
| `POST /listings` (+ accept/withdraw/settle) | ✗ | ✗ (403) | ✓ | **✗ (403)** | **404/RLS** |
| `GET/POST /auto-accept`, `DELETE /auto-accept/{id}` | ✗ | ✗ (403) | ✓ | **✗ (403)** | **404/RLS** |

## Invarianten (KONZEPT §5.10/§5.9)
- **Σ aller Salden inkl. Escrow konstant & nie negativ** (Escrow nur über `economy.api.transfer` mit
  Deckungsprüfung). **Property-Test** (`test_marketplace_properties.py`).
- Statusmaschine vollständig; Escrow-Buchung **atomar** mit dem Statuswechsel; 409-Wächter gegen
  Doppel-Settle/Withdraw; kein Doppel-Listing.
- `marketplace` liest/schreibt **nie** fremde Tabellen direkt (nur via `*.api`); kein Modul importiert
  marketplace (import-linter).

## Tests
- `test_marketplace_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers).
- `test_marketplace_properties.py` — **Hypothesis:** Σ inkl. Escrow == 0, nie negativ über beliebige
  fund/list/accept/settle/withdraw-Folgen.
- `test_marketplace_http.py` — voller Lebenszyklus (list→accept→complete→settle; Käufer erhält Basis +
  Escrow), Rückzug refundet, Pleite-Verkäufer 422, Eigen-Kauf 422, Doppel-Settle 409; **Auto-Accept**
  feuert beim Listing, respektiert `max_price`, Fairness-Tiebreaker wählt den am wenigsten Belasteten.

## Offene Punkte (späterer Worker-Slice)
- **Auto-Settle** bei Erledigung (Composition-Root-Event-Handler) + **zeitlicher** Verfall per Cron.
  Der Zustand `reverted` selbst ist seit 11-S1b erreichbar (`revert_listing`, Anlass: Austritt des
  Käufers) — was fehlt, ist der **Zeitablauf** als Auslöser, nicht der Weg dorthin.
