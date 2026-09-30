# Löschkonzept

> Was geschieht, wenn eine Person ihr Konto löscht — technisch, nachprüfbar und ohne Zusagen, die
> der Code nicht hält. Rechtsgrundlage: Art. 17 DSGVO, KONZEPT §5.1 und §9.
>
> Diese Datei beschreibt beide Wege: die **Kontolöschung** einer Person (11-S1c/d) und die
> **Auflösung eines Haushalts** (11-S1e Zugang, 11-S1f Ausräumen). Sie laufen getrennt und
> unabhängig — ein Konto überlebt die Auflösung seines Haushalts, ein Haushalt überlebt die
> Löschung eines Mitglieds.

## Der Ablauf in drei Stufen

| Wann | Was | Wo |
|---|---|---|
| **Sofort**, mit dem Antrag | Konto gesperrt, alle Sitzungen widerrufen, **Austritt aus allen Haushalten** | `DELETE /v1/auth/account` (11-S1c) |
| **Sofort**, bei einer Haushalts-Auflösung | Haushalt getombstonet, **alle** Mitgliedschaften beendet, **alle** Sitzungen widerrufen, Kinder-Konten vorgemerkt, Ökonomie über alle Mitglieder abgewickelt | `POST /v1/household/dissolve` (11-S1e, ADR-0085) |
| Sofort, als Folge des Austritts | ICS-Feed-Token entwertet, CalDAV-Abos stillgelegt, Art.-9-Wearable-Daten hart gelöscht, Handelspositionen aufgelöst, Restpunkte verfallen als Buchung | `member.left`-Handler + `app/member_exit.py` (11-S1a/b) |
| Nach **30 Tagen** Karenz | Endgültiges Ausräumen: personenbezogene Zeilen gelöscht, `users`-Zeile anonymisiert | `purge_due_accounts_job`, täglich 03:30 (11-S1d) |
| Nach **30 Tagen** Karenz, bei einer Auflösung | Alle 39 zu löschenden haushaltsgebundenen Tabellen geleert, `households`-Zeile entfernt; `audit_log` und `consents` bleiben | `purge_due_households_job`, täglich 04:00 (11-S1f, ADR-0086) |

**Warum der Austritt sofort geschieht und nicht erst nach der Karenz.** Die Frist schützt davor,
dass jemand sein *Konto* aus Versehen wegwirft. Sie ist kein Grund, dreißig Tage lang weiter
Gesundheitsdaten einer Person abzuholen, die gerade Löschung verlangt hat — und der ICS-Token ist
unauthentifiziert, an nichts gebunden und ohne Ablaufdatum.

**Die Kehrseite, die gesagt gehört:** damit ist der Antrag **nicht zurücknehmbar**. Die Person ist
ab dem Antrag aus allen Haushalten heraus.

## Was gelöscht wird und was bleibt

Die Entscheidung fällt **je Spalte**, nicht je Tabelle, und steht vollständig in
`backend/app/deletion_policy.py`. Drei Antworten:

- **`delete`** — die Zeile ist *über* die Person und hat für den Haushalt keinen Wert:
  Sitzungen, Passkeys, Recovery-Codes, Anmelde-Historie, Mitgliedschaften, persönlicher
  Eingangskorb, Automatik-Regeln, ICS-Feed, CalDAV-Abo, Tresor-Schlüsselumschlag, Lesebestätigungen,
  Wearable-Verbindung und -Tageswerte, Rückmeldungen an den Betreiber, **persönliche** Kalendertermine.
- **`keep`** — geteilter Bestand oder Nachweis. Er bleibt und zeigt danach auf die anonymisierte
  Zeile: Einkaufsliste, erledigte Aufgaben, Notizen, Kommentare, Anleitungen, Tresor-Einträge,
  Wochenplan, zugestellte Briefe, **Haushalts**-Kalendertermine — und der Punkte-Ledger.
- **`operator`** — keine Entscheidung, sondern eine Feststellung: die Spalte verweist auf ein
  Betreiber-Konto, nicht auf ein Haushaltsmitglied.

### Warum die `users`-Zeile stehen bleibt

Sie wird **anonymisiert, nicht gelöscht**: E-Mail, Benutzername, Passwort-Hash, PIN-Hash,
TOTP-Geheimnis, Profileinstellungen und die Bestätigung der E-Mail-Adresse werden geleert,
`purged_at` gesetzt. Die Zeile selbst bleibt.

Der Grund ist konkret: **31 Spalten verweisen auf eine Person, und nur vier haben einen
Fremdschlüssel.** Würde die Zeile verschwinden, zeigten 27 Verweise ins Leere — ohne dass die
Datenbank es merkte. Die anonymisierte Zeile hält sie gültig und sagt nichts mehr über die Person.

KONZEPT §5.1 verlangt genau das: Beiträge bleiben zugeordnet, der Name wird pseudonym.

**Der Ersatzname steht nicht in der Datenbank.** `display_name` wird *geleert*, nicht auf
„Ehemaliges Mitglied" gesetzt — das fröre einen deutschen Anzeigetext in einer DE+EN-Anwendung ein
und machte ihn zum Löschzeitpunkt unveränderlich. Der Ersatztext gehört in den i18n-Katalog,
dieselbe Regel wie bei `BRAND_NAME`.

### Der Punkte-Ledger

Bei der **Kontolöschung** wird er nie gelöscht. Er ist eine append-only Doppelbuchung (ADR-0035): jede Bewegung hat zwei
Konten. Eine Buchung der ausscheidenden Person zu entfernen veränderte die Salden **anderer** — ein
Danke-Punkt gehört beiden Seiten. Deshalb steht `points_ledger` auch ausdrücklich nicht in der
Retention-Liste des Reapers. Der Restsaldo wird stattdessen beim Austritt als eigene Buchung
entwertet (`ref_type='member_exit'`, 11-S1b).

**Beim Haushalts-Purge fällt er dagegen mit** (11-S1f, ADR-0086 §6). Das ist kein Widerspruch,
sondern dieselbe Begründung zu Ende gedacht: die Regel schützt die Salden **anderer** Konten —
nach der Auflösung gibt es keine. Personenbezogen ist der Ledger über die Kontostrings
`member:<uuid>` und `created_by`; eine `member_id`-Spalte hat er nicht.

## Wie die Vollständigkeit erzwungen wird

Drei Prüfungen, alle blockierend in CI, alle **gegen die echte Datenbank** — nicht gegen das ORM.
Das ORM kennt 29 Spalten des Schemas nicht; genau dort saßen beim Datenexport `tenancy_probe` und
`guides.search_tsv`.

1. **Jede Verweis-Spalte muss eingeordnet sein.** Jede Spalte auf `_id`/`_ids` braucht entweder
   eine Löschregel oder einen ausdrücklichen Eintrag als Sachbezug. Schweigen ist keine Antwort.
   *Die erste Fassung dieses Gates listete Namens-Suffixe und nannte sich „absichtlich zu breit" —
   sie war es nicht: neun Personenbezüge (`author_id`, `from_id`, `cook_id`, `contact_id` …) fielen
   durch. Ein Muster, das „zu breit" heißt, muss zu breit bewiesen werden.*
2. **Die Rechte werden gemessen, nicht geglaubt.** Postgres prüft Tabellenrechte beim **Planen**,
   nicht beim Treffer — ein fehlendes DELETE lässt den Job scheitern, auch wenn nichts zu löschen
   wäre, und ein Job, der nur bei Wirkung loggt, sieht dabei aus wie einer, der nichts zu tun fand.
   Genau daran ist der Retention-Reaper monatelang gestorben (BUGLOG 2026-07-31). Vor Migration
   0072 hatten **4 von 14** Purge-Tabellen ein DELETE-Recht und vier gar keine Policy.
3. **Ein Export nach der Löschung.** Der stärkste Test des Strangs: er hält Klassifizierung und
   Purge *gegeneinander*. Eine Tabelle, die in **beiden** Listen vergessen wurde, fällt nirgendwo
   sonst auf — beide Testreihen blieben grün.

## Betriebsverhalten

- **Ein Konto je Transaktion.** Innerhalb eines Kontos gilt alles-oder-nichts: ein halb
  ausgeräumtes Konto wäre schlimmer als ein gescheiterter Lauf. Zwischen Konten gilt das Gegenteil
  — ein Konto, das an einer Besonderheit scheitert, darf die anderen dieser Nacht nicht mitreißen.
- **Fehlschläge werden gemeldet**, nicht verschwiegen: `account_purge_failed` mit Kontenzahl und
  SQLSTATE je Fall. Der SQLSTATE ist ein fünfstelliger Code und nie Inhalt — der Fehler*text* wäre
  es, weil Postgres bei Constraint-Verletzungen die betroffene Zeile anhängt.
- **Idempotent.** `users.purged_at` trennt „vorgemerkt" von „erledigt"; ein zweiter Lauf findet
  nichts. Ohne die zweite Spalte sähe jede Nacht dieselbe Zeile wieder als fällig.
- Der Cron läuft um **03:30**, versetzt zum Retention-Reaper um 03:00 — beide laufen als
  `custode_maint` über teils dieselben Tabellen.

## Aufbewahrungsfristen

| Was | Frist | Umsetzung |
|---|---|---|
| Karenz bis zum endgültigen Löschen | 30 Tage (`retention_days`) | `purge_due_accounts_job` |
| Getombstonete Fachzeilen („Papierkorb") | 30 Tage | `reap_deleted_job` (Tabellenliste `_RETENTION_TABLES`) |
| Wearable-Rohwerte (Art. 9) | 90 Tage | `wearable_retention_job` |
| Outbox / Sync-Idempotenz | 30 Tage | eigene Reaper |

## Nachtrag

- ~~**Haushaltsauflösung Phase 2** (11-S1f)~~ — **erledigt am 2026-08-02** (ADR-0086). Der Cron um
  04:00 räumt aufgelöste Haushalte nach der Karenz aus: Menge zur Laufzeit aus dem Katalog
  abgeleitet, Reihenfolge topologisch aus `pg_constraint`, gelöscht als `custode_app` unter RLS
  (das DELETE nennt den Haushalt nicht — die Policy tut es), und der Durchgang wiederholt sich **je
  Mitglied**, weil zwei Tabellen mitglieds-gescopt sind. `points_ledger` und die `households`-Zeile
  fallen; `audit_log` und `consents` bleiben und sind für `custode_app` ohnehin gesperrt. Keine
  Migration, keine neuen Rechte. **Art. 17 ist damit für Person und Haushalt vollständig gebaut.**
  Die Zahlen dahinter, gegen eine frisch migrierte Datenbank gemessen: 41 Tabellen mit
  `household_id`, **0** Fremdschlüssel auf `households.id` (die Datenbank kann eine vergessene
  Tabelle also nie melden — deshalb die Ableitung statt einer Liste), 5 reihenfolgebindende
  `NO ACTION`-Kanten, und ein Trockenlauf, nach dem `custode_app` auf **40 von 42** Zielen löschen
  darf. Ausführlich in ADR-0086 und `KONFIG/Roadmap_to_V0.1.md`.
- **Tresor-Schlüssel-Rotation** beim Austritt (KONZEPT §5.1) ist ein eigener Slice — der
  Warnhinweis im Tresor sagt das ausdrücklich, statt eine Rotation zu behaupten.
