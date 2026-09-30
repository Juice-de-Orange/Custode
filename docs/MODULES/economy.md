# Modul `economy`

**Status:** in Arbeit · **Phase:** 4 · **KONZEPT:** §5.9

## Zweck & Verantwortung
Punkte-Ökonomie des Haushalts (KONZEPT §5.9): **append-only Doppelbuchungs-Ledger** (`points_ledger`).
Erste Quelle = Task-Erledigung (System → Mitglied); spätere Senken/Transfers: Belohnungs-Einlösung
(P4-S3), Marketplace-Escrow (P4-S8), Danke-Punkte (P4-S4). P4-S2 = Ledger + Saldo-Lesepfad + synchrone
Gutschrift bei Task-Erledigung + Admin-Korrektur.

## Datenobjekte (Migrationen 0024 + 0025)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `points_ledger` | id (uuidv7); eine Bewegung = eine Zeile `from_account→to_account`, `amount>0` (CHECK), `from≠to` (CHECK); `ref_type`/`ref_id` = Fachbezug; **append-only** (nie UPDATE/DELETE) | `household_id = app.household_id` |
| `rewards` (0025) | admin-definiert; `cost>0` (CHECK); optional `stock`/`cooldown_hours`; `version` = ETag (PATCH+If-Match); Soft-Delete | `household_id = app.household_id` |
| `redemptions` (0025) | `reward_id`→`rewards`; `member_id`; `title`/`cost` **Snapshot**; Status `requested→fulfilled`; nie hard-deleted | `household_id = app.household_id` |

Konten als Strings: `system` (Schöpfung/Senke), `member:<uuid>`, `escrow:<listing_id>`. Standard-Mixin
(`version`/`updated_at`/`deleted_at` ungenutzt — Zeilen werden nie geändert). Indizes für Saldo-Summen
`(household_id, from_account)` / `(household_id, to_account)`. RLS-Negativtest (`test_economy_rls.py`:
A↛B → 0; WITH CHECK gegen Fremd-Haushalt).

## Schreibpfad
- **Synchron via `economy.api` (ADR-0035)** — `tasks.complete_instance` ruft
  `credit_task_completion(system→member:done_by)` in derselben Tx (atomar, exakt-einmal über den
  409-Wächter, Saldo sofort). Kein Sync-Batch, kein PATCH+If-Match (Ledger ist nicht editierbar).
- `transfer(...)` ist der **einzige** Schreibpfad: positiver Betrag, `from≠to`, **Deckungsprüfung** bei
  Member-/Escrow-Quelle (`balance(from) ≥ amount`) → sonst **422** (`insufficient_funds`). Nur `system`
  schöpft ohne Deckung.

## Schnittstellen
- **HTTP `/v1/economy` (`router.py`):** `GET /balance` · `GET /ledger?limit=` · `POST /corrections`
  (**admin**, Grant/Claw-back als sichtbare Gegenbuchung). **Belohnungen (P4-S3):** `GET /rewards`
  (Mitglieder: aktive; Admin: alle) · `POST /rewards` (**admin**, 201, +ETag) · `GET /rewards/{id}` ·
  `PATCH /rewards/{id}` (**admin**, If-Match) · `DELETE /rewards/{id}` (**admin**, Soft-Delete) ·
  `POST /rewards/{id}/redeem` (member; Deckung + Stock + Cooldown) · `GET /redemptions?status=`
  (Admin: Haushalt = Bestätigungsliste; Member: eigene) · `POST /redemptions/{id}/fulfill` (**admin**).
- **Danke-Punkte + Wochen-Challenge (P4-S5):** `POST /thanks` (member→member, Deckung + Wochen-Cap
  10 P/ISO-Woche; 422 bei Cap/Selbst) · `GET /challenge` (Live-Wertung: pro Mitglied diese ISO-Woche
  aus `task_completion` verdiente Punkte, absteigend; + eigenes Danke-Restkontingent).
- **Fairness-Konto (P4-S6/S7):** `GET /fairness` (je Mitglied Last = `task_completion`-Punkte über
  ein 30-Tage-Fenster, **aufsteigend** = wer am wenigsten getragen hat, ist als Nächstes dran).
  Live aus dem Ledger; Abwesenheits-Herausrechnung = Phase 5 (braucht Kalender).
- **Services (`api.py`):** `balance`, `transfer`, `credit_task_completion`, `fairness_load`,
  `member_account`, `escrow_account` (`fairness_load` = Tiebreaker-Input für den Marketplace, S8).
  (Rewards/Redemptions/Thanks/Challenge sind economy-intern — kein api.py-Export.)
- **Events:** `reward.changed`, `reward.redeemed` → SSE-Entity `"rewards"`; `thanks.sent` → `"economy"`
  (Saldo + Challenge live). Buchung synchron; Saldo/Challenge-SSE auch über den `tasks`-Hint.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member | admin | fremder Haushalt |
|---|---|---|---|---|---|
| `GET /balance`, `GET /ledger` | ✗ (401) | ✗ (403) | ✓ (eigener) | ✓ | **RLS: nur eigener Haushalt** |
| `POST /corrections` | ✗ | ✗ (403) | **✗ (403)** | ✓ | **RLS** |

## Invarianten (KONZEPT §5.9 — Tabu bei Verletzung)
- **Salden sind SUMMEN** (`Σ to − Σ from`), nie ein gespeichertes/editierbares Feld.
- `amount > 0`; **keine negativen Salden** (Deckungsprüfung). Jede Bewegung referenziert ein Fachereignis.
- **Append-only:** kein UPDATE/DELETE; Korrektur nur als Gegenbuchung. **Punkte ↛ Geld** (N-1).
- **Die eine Ausnahme, und sie ist keine Aufweichung:** append-only regelt **Korrekturen im
  lebenden Ledger** — eine Buchung wird nie überschrieben, sondern gegengebucht, weil jede zwei
  Konten hat und ein Löschen die Salden **anderer** verschöbe. Genau deshalb lässt der Austritt
  Restpunkte als *Buchung* verfallen (`ref_type='member_exit'`, 11-S1b) statt sie zu löschen.
  Endet der **Mandant**, gibt es keine anderen Salden mehr, die stimmen müssten: beim
  Haushalts-Purge (11-S1f, ADR-0086 §6) fallen `points_ledger`, `rewards`, `redemptions` und
  `market_listings` mit. Eingeordnet in `app/household_deletion_policy.py` — der Code zitiert diese
  Regel dort namentlich.

## Tests
- `test_economy_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers PG18).
- `test_economy_properties.py` — **Hypothesis-Property-Tests:** Doppelbuchung summiert auf 0 (inkl.
  system/escrow); Saldo = `Σ to − Σ from`; Coverage hält Member/Escrow ≥ 0.
- `test_economy_http.py` — Erledigen bucht (Saldo steigt, Ledger-Eintrag); 0-Punkte bucht nichts;
  Admin-Grant/Claw-back; Claw-back unter 0 → 422 (Saldo unverändert).
- Web: `realtime-map.test.ts` (`tasks → […, BALANCE_QUERY_KEY]`).

## Offene Punkte (Folge-Slices)
- **P4-S3 ✅** Belohnungskatalog + Einlösung. **P4-S4 ✅** Wert-Verfall (in `tasks`).
- **P4-S5 ✅** Danke-Punkte + Wochen-Challenge. **P4-S7 ✅** Fairness-Konto (`fairness_load`, 30-Tage-
  Fenster, aufsteigend; Tiebreaker für S8). **Offen:** Challenge an/aus + Gewinner-Belohnung; Kinder-
  Wochenziele; Abwesenheits-Herausrechnung (Phase 5).
- **P4-S8** Marketplace-Escrow nutzt `transfer(member→escrow→buyer)` + `fairness_load` (Auto-Accept-Tiebreaker).
