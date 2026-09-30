# ADR-0071 — Betreiber-Konsole: Aggregat-Views + DB-Rollen-Trennung (Fundament)

**Status:** beschlossen · **Phase:** 8 (P8-S7a) · **Datum:** 2026-06-29
**Kontext-KONZEPT:** `ARCHITECTURE` §8.6 (Backoffice-Pfad), §9 (RLS, separate DB-Rollen), §12
(Metriken), **ADR-0015** (Betreiber liest nur Aggregat-Views, nie Fachdaten). Roadmap Phase 8
(„Ops-Console v1"). Realisiert die in ADR-0015 getroffene Grenze auf DB-Ebene.

## Kontext
Die Betreiber-Konsole braucht Kennzahlen (Haushalte, Nutzer, Signup-Kurve), darf aber **niemals**
einzelne Fachzeilen sehen (ADR-0015, Mandantentrennung). Das ist ein DB-Design-Problem: Aggregate
über **alle** Haushalte erfordern, RLS zu überwinden — aber die Ops-Rolle selbst darf keine
Fachtabelle lesen.

## Entscheidung

### Zwei DB-Rollen `ops_readonly` / `ops_actions`
Provisioniert in `infra/postgres/init.sql` als `LOGIN NOSUPERUSER NOBYPASSRLS`, **ohne** jegliches
Fachtabellen-Recht (das `GRANT … ON ALL TABLES` gilt nur für `custode_app`). `ops_readonly` = Lesen
(KPIs/Health, S7a/S7b); `ops_actions` = auditierte Aktions-Prozeduren (S8).

### Aggregat-Views als **security definer**, Owner = `custode_maint`
Migration 0055 legt `usage_counters` (Einzelzeile: Haushalte/Nutzer/erwachsene Mitglieder/Kinder)
und `daily_metrics` (neue Haushalte/Nutzer je Tag) an. Die Views laufen als **security definer**
(`security_invoker` aus) und gehören **`custode_maint`**: beim Abfragen greifen die Tabellenzugriffe
mit dessen Rechten **und** `maint_all`-Policies (USING true, Migrationen 0006/0007) → **alle**
Haushalte sichtbar, ohne `app.household_id`. `ops_readonly` erhält **SELECT nur auf die Views** —
kein Fachtabellen-Grant. Ergebnis: Kennzahlen ja, einzelne Zeilen nein.

**Warum `custode_maint`-Owner statt Superuser-Owner:** ein Superuser-Owner würde RLS via Superuser
umgehen — funktioniert in CI (Migration läuft als Superuser), aber in Prod ist der Migrations-/
Tabellen-Owner kein Superuser und unterliegt `FORCE RLS` → Aggregate wären leer. `custode_maint` hat
genau die `maint_all`-Policies, die haushaltsübergreifendes Aggregieren **umgebungsunabhängig**
erlauben. Der Owner-Wechsel braucht kurz `CREATE ON SCHEMA public` für `custode_maint` (im selben
`DO`-Block erteilt und sofort wieder entzogen; das Eigentum bleibt).

### Negativtest (Sicherheits-Gate)
`tests/test_ops_isolation.py`: `ops_readonly` liest `usage_counters`/`daily_metrics` korrekt
(Aggregate über alle Haushalte), aber `SELECT` auf `households`/`users`/`memberships` schlägt mit
`InsufficientPrivilege` fehl. Das ist der DoD-Beweis der Ops-Grenze.

## Konsequenzen
- **Plus:** ADR-0015 ist auf DB-Ebene **erzwungen** (nicht nur App-Konvention); ein Ops-Bug kann keine
  Fachzeile leaken. Wiederverwendet die etablierten `maint_all`-Policies, kein neuer BYPASSRLS-Rolle.
- **Plus:** Umgebungsunabhängig korrekt (CI-Superuser **und** Prod-Owner).
- **Minus:** `custode_app` erhält über `ALTER DEFAULT PRIVILEGES` (init.sql) implizit SELECT auf die
  Views — unkritisch (nur globale Aggregate, keine PII/Fachzeilen), aber nicht beabsichtigt; ggf.
  später entzogen.
- **Minus:** Metrik-Umfang v1 ist klein (Konten + Signup-Kurve aus Tabellen, die `maint` schon sieht).
  Task-/Nutzungs-Metriken brauchen weitere `maint_all`-Policies **oder** eine Rollup-Tabelle (später).
- **Offen (S7b/S8):** Operator-Auth-Stack (`operators`, Passkey+TOTP, `/ops`-Router), Build-Info/Health
  hinter `/ops`, Aktions-Prozeduren über `ops_actions` mit `audit_log`.

## Alternativen
- **Superuser-Owner-Views:** in Prod nicht zuverlässig (Owner kein Superuser, FORCE RLS); verworfen.
- **Eigene BYPASSRLS-View-Owner-Rolle:** zusätzliche hochprivilegierte Rolle; unnötig, da `custode_maint`
  via `maint_all` reicht. Verworfen (geringste Rechte).
- **Rollup-Metrik-Tabelle per Job:** mehr Maschinerie; für v1-Kennzahlen über bereits sichtbare
  Tabellen nicht nötig — bleibt Option, sobald Metriken über RLS-geschützte Module nötig werden.
