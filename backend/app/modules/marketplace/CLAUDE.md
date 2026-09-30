# CLAUDE.md — Modul `marketplace`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Handelbare Haushaltsaufgaben mit Escrow (KONZEPT §5.10): ein Mitglied verkauft eine ihm zugewiesene,
offene Task-Instanz zu einem Preis; der Käufer übernimmt die Aufgabe und erhält bei Erledigung den
Escrow. P4-S8a = Listing/Escrow + Statusmaschine (open→accepted→settled / open→withdrawn);
P4-S8b = Auto-Übernahme-Regeln + Fairness-Tiebreaker (synchron).

## Grenzen (hart)
- Importiert **nur** `kernel/*` + die **öffentliche** `tasks.api` (Instanz prüfen/zuweisen) und
  `economy.api` (Escrow buchen) — **nie** deren Interna, nie ein anderes Modul. **Kein Modul importiert
  marketplace** (einseitige Abhängigkeit `marketplace → tasks/economy` → **kein Zyklus**; import-linter).
- `market_listings` trägt `household_id`; RLS aktiv (`FORCE`), Negativtest.

## Datenmodell (Migrationen 0028 + 0029)
- `market_listings`: `task_instance_id` (reine ID, **kein** Cross-Modul-FK), `seller_id`, `price>0`
  (CHECK), `status ∈ {open,accepted,settled,reverted,withdrawn}`, `buyer_id?` (+ Standard-Mixin).
- `auto_accept_rules` (0029): `member_id`, `template_id?` (NULL = jede Aufgabe), `max_price>0` (CHECK),
  `active` (+ Standard-Mixin). Matcht ein neues Listing → sofortiger Zuschlag; bei mehreren Treffern
  entscheidet `economy.api.fairness_load` (geringste Last, Tiebreak per `user_id`, Audit A-05).

## Escrow (über das economy-Ledger, ADR-0035)
- **Listing:** `member:seller → escrow:<listing_id>` (Preis reservieren; Deckungsprüfung → kein
  negativer Saldo, kein Doppel-Listing).
- **Annehmen:** Task wird via `tasks.api.reassign_instance` dem Käufer zugewiesen; Escrow bleibt gesperrt.
- **Settle (Task erledigt):** `escrow → member:buyer` (Käufer behält zusätzlich die Basis-Punkte aus der
  Erledigung, Audit A-04).
- **Rückzug (offen):** `escrow → member:seller`.
- **Rückabwicklung** (`accepted→reverted`) gibt es seit 11-S1b: `revert_listing` bucht das Escrow
  an den Verkäufer zurück und gibt ihm die Aufgabe. Der Zustand stand seit Migration 0028 im CHECK,
  ein Codepfad dorthin existierte nie. Erster Anlass ist der **Austritt des Käufers**: `settle`
  zahlte sonst an ein Konto, das nicht mehr besetzt ist, und die Aufgabe hinge an jemandem, der sie
  nicht erledigen kann. Ein zeitlicher Verfall per Cron ist damit **nicht** gebaut — nur der
  Austrittspfad.
  **Ihr Vertrag ist „nicht geliefert" (seit 2026-08-03, BUGLOG).** Ist die Instanz `done`, lehnt
  `revert_listing` mit 409 `task_already_done` ab: ein erfüllter Handel gehört abgerechnet, sonst
  bekäme der Verkäufer die erledigte Arbeit **und** seine Punkte zurück. Eine **getombstonete**
  Instanz ist dagegen kein Fehler — zurückzugeben ist nichts, aber das Escrow muss trotzdem los.
- **`api.py` ist nicht mehr leer:** `release_positions_of(household_id, member_id)` löst beim
  Austritt beide Rollen auf — offene **Verkäufe** zurückziehen, angenommene **Käufe**
  rückabwickeln **oder abrechnen**. Als Verkäufer eines bereits angenommenen Listings passiert
  bewusst nichts: das Escrow hat das Konto längst verlassen, der Handel kommt ohne die Person zu
  Ende.
  **Die Verzweigung beim Kauf ist der Inhalt der Funktion, nicht ihre Verpackung:** hat der
  Käufer geliefert (`tasks.api.instance_status == "done"`), wird abgerechnet — es gibt **kein
  Auto-Settle**, der Zustand *erledigt, aber nicht abgerechnet* ist der Normalfall zwischen zwei
  Klicks. Vorher lief hier ausnahmslos `revert_listing`, und der 409 aus `reassign_instance` riss
  den ganzen Austritt in die DLQ (bei der Haushalts-Auflösung den **aller** Mitglieder, weil die in
  einer Transaktion läuft).

## Schnittstellen (HTTP)
- `/v1/marketplace/listings`: `GET ?status=` (default open) · `POST` (anlegen) ·
  `POST {id}/accept` · `POST {id}/withdraw` · `POST {id}/settle`. Alle **member/admin** (Kinder ✗:
  `marketplace_children` default off), CSRF auf Writes.
- `/v1/marketplace/auto-accept`: `GET` (eigene Regeln) · `POST` (anlegen) · `DELETE {rule_id}`.
  Ebenfalls **member/admin** (Kinder ✗), CSRF auf Writes.

## Events
- **publiziert:** `market.listing.created`, `market.listing.sold`, `market.trade.settled`,
  `market.trade.reverted` (seit 11-B4 — KONZEPT §5.10 nennt ihn, der Code emittierte bis dahin
  dasselbe inhaltslose `market.changed` wie beim Rückzug) und `market.changed` (Rückzug)
  → SSE-Entity `"marketplace"`. **abonniert:** — (Settle ist in S8a explizit; das
  event-getriebene Auto-Settle bei Erledigung = S8b über die Composition-Root-Registrierung).
- **Ein Ereignistyp ohne Eintrag in `kernel/events/handlers.py::_ENTITY_BY_TYPE` verpufft stumm.**
  `tests/test_event_catalogue.py` haelt beide Richtungen: unklassifiziert = rot, Eintrag ohne
  Emission = rot.

## Invarianten (KONZEPT §5.10/§5.9)
- **Σ aller Salden inkl. Escrow konstant & nie negativ** (Escrow nur über `economy.api.transfer`,
  Deckungsprüfung). Property-Test.
- Statusmaschine vollständig; kein Doppel-Listing (offenes Listing je Instanz eindeutig).
- Escrow-Buchung **atomar** mit dem Statuswechsel (eine Tx).

## No-Gos
- **Nie** Salden/Escrow als Feld speichern — immer über das append-only Ledger.
- **Nie** die tasks-/economy-Tabellen direkt lesen/schreiben (nur via deren `api.py`).
- Kinder nicht handeln lassen (Default off).
