# ADR-0073 — Append-only Audit-Log für Betreiber-Aktionen & Sicherheitsereignisse

**Status:** beschlossen · **Phase:** 8 (P8-S8a) · **Datum:** 2026-06-29
**Kontext-KONZEPT:** `ARCHITECTURE` §8.6 (jede Betreiber-Aktion schreibt `audit_log` + Haushalts-
Transparenz-Log), §12 (Observability), **ADR-0015** (Ops-Grenze), **ADR-0071/0072** (Ops-DB-Rollen,
Operator-Auth). Analogie: das append-only Punkte-Ledger (ADR-0035).

## Kontext
Betreiber-Aktionen (Banner, Flags, Support-Eingriffe — S8) müssen **nachvollziehbar und unveränderbar**
protokolliert werden. Es fehlt eine Audit-Infrastruktur. Anforderungen: append-only (Korrektur nur per
neuer Zeile), kein Zugriff der normalen App-Rolle, kein PII.

## Entscheidung

### Tabelle `audit_log` (Migration 0057), DB-erzwungen append-only
Spalten: `id`, `occurred_at`, `actor_type` (operator|system|user), `actor_id`, `action`,
`target_type`/`target_id`, `household_id` (optional, für haushaltsbezogene Aktionen), `detail_json`
(strukturiert, **kein PII**), `request_id` (Fehler-Referenzcode-Verknüpfung, §12). **Append-only auf
Grant-Ebene:** **keine** Rolle erhält `UPDATE`/`DELETE` — nur `INSERT`/`SELECT` für die ops-Rollen.
Stärker als das Ledger (das per Konvention+Property-Test append-only ist), weil ein Sicherheits-Log
auch gegen einen kompromittierten App-/Ops-Pfad immutabel sein soll.

### Isolation von der App-Rolle
`custode_app` wird per **REVOKE** ausgesperrt (entzieht den `ALTER DEFAULT PRIVILEGES`-Grant aus
`init.sql`). Nur `ops_actions` (INSERT+SELECT) und `ops_readonly` (SELECT) haben Zugriff. Der
Sicherheits-Log ist ops-only; eine App-SQLi kann ihn weder lesen noch fälschen.

### Kernel-Helfer `record_audit`
`kernel/audit/record.py::record_audit(session, …)` (INSERT-only) + Modell `AuditEntry` (kernel,
Querschnitt). Aufgerufen von Betreiber-Aktionen (S8) auf einer `ops_actions`-Session; `detail` ohne
PII (Aufrufer-Pflicht). Schreib-Verbindung über neue `get_ops_actions_sessionmaker`.

## Konsequenzen
- **Plus:** Unveränderbarer, app-isolierter Audit-Trail, DB-erzwungen; bereit für jede S8-Aktion.
- **Plus:** `request_id` verknüpft Audit-Einträge mit dem Fehler-Referenzcode/Trace (§12).
- **Minus:** Die **Haushalts-Transparenz-Sicht** (ein Haushalt sieht ihn betreffende Betreiber-
  Aktionen) ist noch nicht gebaut — `household_id` ist vorbereitet, die household-lesbare Sicht folgt,
  sobald haushaltsbezogene Aktionen existieren (S8+).
- **Minus:** App-seitige Sicherheitsereignisse (Login etc.) laufen heute über `auth_login_events`,
  nicht `audit_log`; eine Vereinheitlichung ist optional/später.

## Alternativen
- **Append-only nur per Konvention (wie Ledger):** schwächer; für einen Sicherheits-Log ist DB-Ebene
  angemessen. Verworfen.
- **Trigger, der UPDATE/DELETE blockt:** funktioniert auch, aber Grant-Entzug ist einfacher und deckt
  alle Pfade. Gewählt: Grants.
- **`audit_log` für `custode_app` lesbar (Transparenz):** würde PII/Sicherheitsdaten der App
  exponieren; Transparenz kommt über eine **separate** haushaltsgescopte Sicht. Verworfen.
