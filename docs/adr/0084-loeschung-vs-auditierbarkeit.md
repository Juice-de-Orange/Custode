# ADR-0084 — Löschung vs. Auditierbarkeit: `audit_log` wird pseudonymisiert, nicht gelöscht

- **Status:** beschlossen · **Phase:** 11 · **Datum:** 2026-07-31
- **Betrifft:** `kernel/audit`, `modules/backoffice`, die kommende Löschkaskade (Art. 17)
- **Bezug:** KONZEPT §9 (Betroffenenrechte, Betreiber-Grenze), [ADR-0073](0073-audit-log.md)
  (append-only Audit-Log), [ADR-0071](0071-ops-aggregate-views.md) (Betreiber-Grenze)

## Kontext

Zwei Pflichten stoßen aufeinander, und beide sind im Repo ausdrücklich beschlossen.

**ADR-0073** macht `audit_log` append-only, und zwar nicht per Konvention, sondern per Grant:
Migration 0057 vergibt `INSERT, SELECT` an `ops_actions`, `SELECT` an `ops_readonly` und entzieht
`custode_app` alles. **Keine Rolle hat UPDATE oder DELETE** — auch nicht die, die schreibt. Das ist
der Punkt: ein Audit, das sein Schreiber nachträglich ändern kann, beweist nichts.

**KONZEPT §9** verlangt „Account-/Haushalts-Löschung mit definierter Kaskade". `audit_log` trägt
`actor_id`, `target_id` und `household_id` — Personenbezug ist ihr Zweck, nicht ihr Nebenprodukt.

Damit gibt es heute **keinen Weg**, eine gelöschte Person aus dem Audit zu entfernen. Nicht „einen
umständlichen" — gar keinen: die Rolle, die die Löschkaskade ausführt, könnte die Zeile nicht
einmal lesen. Kein Dokument im Repo löst das auf; der Konflikt fiel erst bei der Bestandsaufnahme
für Art. 17 auf.

## Entscheidung

**Der Personenbezug wird ersetzt, die Zeile bleibt.** Beim endgültigen Löschen einer Person
ersetzt ein Wartungspfad `actor_id` und `target_id` durch ein Pseudonym ohne Rückweg; `household_id`
bleibt, weil sie den Haushalt bezeichnet, nicht die Person.

Vier Festlegungen dazu:

1. **Der Pfad läuft nicht unter `ops_actions`.** Die Rolle behält `INSERT, SELECT` und sonst
   nichts — sonst wäre die Append-only-Zusage aufgegeben, um sie einmal jährlich zu umgehen. Die
   Ersetzung läuft als **Migrations-/Wartungsschritt** unter der Owner-Rolle, angestoßen vom
   Lösch-Job, und ist selbst ein Audit-Ereignis (`subject.pseudonymised`).
2. **Irreversibel.** Kein Mapping alt→neu wird irgendwo abgelegt. Ein Pseudonym, dessen Auflösung
   man aufbewahrt, ist kein Pseudonym, sondern eine zweite Kopie.
3. **Der Verlauf bleibt lückenlos.** Wer wann was tat, ist weiterhin nachvollziehbar — nur nicht
   mehr, *welcher Mensch* es war. Für den Zweck des Logs (Missbrauchserkennung, Nachweis der
   Betreiber-Grenze) genügt das; für Art. 17 genügt es ebenfalls, weil die Zeile die Person nicht
   mehr identifiziert.
4. **Das Verfahren wird dokumentiert, nicht versteckt.** Es gehört in `docs/LOESCHKONZEPT.md` (die
   von KONZEPT §9 verlangte Tabelle je Entität), in die DSFA und in das Runbook „Haushalt auf
   Anfrage löschen".

## Konsequenzen

- **Positiv:** Beide Zusagen bleiben stehen. Das Audit ist weiterhin für jede Rolle
  unveränderlich, die im Betrieb darauf schreibt — und trotzdem enthält es nach einer Löschung
  keinen Personenbezug mehr.
- **Positiv:** Art. 17 kennt die Abwägung gegen berechtigte Aufbewahrung ausdrücklich. Ein
  Sicherheitsprotokoll ist ein anerkannter Aufbewahrungsgrund; die Pseudonymisierung ist das
  mildere Mittel gegenüber „gar nicht löschen" und gegenüber „Beweiskraft aufgeben".
- **Kosten:** Ein privilegierter Pfad außerhalb der App-Rollen. Er ist eng: eine Anweisung, ein
  Aufrufer, ein Audit-Eintrag über sich selbst. Aber er existiert, und das ist eine bewusste
  Ausnahme, keine Selbstverständlichkeit.
- **Grenze, benannt:** `household.searched` (Support-Suche) trägt gar keine Haushalts-ID, nur
  `query_length` und `result_count`. Ein Haushalt, der in einer Trefferliste auftauchte, ohne
  geöffnet zu werden, ist im Log nicht rekonstruierbar — und damit auch nicht pseudonymisierbar.
  Das ist hinnehmbar (die Zeile enthält keinen Personenbezug), gehört aber gesagt.

## Alternativen (verworfen)

- **Aufbewahrungsfrist statt Löschung** (`audit_log` läuft nach 12 Monaten als Ganzes aus).
  Einfacher, aber der Personenbezug bliebe bis zum Fristende bestehen — bei einem Menschen, der
  ausdrücklich Löschung verlangt hat. Und eine Frist löst das Problem nicht, sie verschiebt es.
- **`DELETE` für `ops_actions` freigeben.** Ehrlich in der Wirkung, aber es gibt genau die
  Eigenschaft auf, die das Audit beweiskräftig macht: dass sein Schreiber es nicht ändern kann.
  ADR-0073 hätte damit keinen Inhalt mehr.
- **Zeilen mit Personenbezug gar nicht erst schreiben.** Dann fiele die Betreiber-Grenze als
  nachweisbar aus — ein Audit, das nicht sagt, *wer* auf einen Haushalt geschaut hat, belegt
  nichts. KONZEPT §9 nennt genau diese Nachweisbarkeit „verbindlich".
