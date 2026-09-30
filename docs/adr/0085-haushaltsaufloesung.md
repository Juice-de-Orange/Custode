# ADR-0085 — Haushalts-Auflösung: Selbstbedienung, zweistufig, und die Mandantengrenze bleibt RLS

- **Status:** beschlossen · **Phase:** 11 · **Datum:** 2026-08-01
- **Betrifft:** `modules/accounts`, `kernel/deletion`, der Composition Root, Web `/account`
- **Bezug:** KONZEPT §5.1 (Auflösung, in dieser Runde ergänzt), §9 (Betroffenenrechte),
  [ADR-0083](0083-datenexport-betroffenenrechte.md) (RLS statt WHERE-Klausel),
  [ADR-0084](0084-loeschung-vs-auditierbarkeit.md) (`audit_log` überlebt),
  [ADR-0039](0039-composition-root.md) (Quermodul-Abläufe am Composition Root),
  [ADR-0035](0035-punkte-ledger.md) (append-only Doppelbuchung)

## Kontext

Zwei Abweisungen im Code verweisen auf eine Funktion, die es nicht gibt: der Selbst-Austritt lehnt
für Alleinstehende mit `sole_member` ab, die Kontolöschung mit `only_children`. Beide sagen sinngemäß
„dieser Haushalt muss aufgelöst werden" — und **niemand kann das**. Bei `only_children` ist das
nicht bloß unbequem, sondern sperrt eine Person aus ihrem Art.-17-Recht aus.

Eine Bestandsaufnahme gegen eine frisch migrierte Datenbank hat drei Tatsachen ergeben, die den
Entwurf bestimmen:

1. **41 Tabellen tragen `household_id`** — und **kein einziger Fremdschlüssel zeigt auf
   `households.id`.** Das Löschen der Haushaltszeile kaskadiert nichts und wird von nichts
   blockiert. Die Datenbank kann eine vergessene Tabelle **nie** melden.
2. **Fünf Fremdschlüssel auf `NO ACTION` erzwingen eine Reihenfolge** (u. a. die dreistufige Kette
   `task_instances → task_templates → rooms`). Keiner ist `DEFERRABLE`; die Reihenfolge bindet auch
   innerhalb einer Transaktion. Empirisch geprüft: richtige Reihenfolge löscht 41 Tabellen
   fehlerfrei, umgekehrte scheitert an zwei Constraints.
3. **`custode_app` löscht Wearable-Zeilen nur die eigenen** — die Policy ist mitglieds-gescopt
   (ADR-0081). Ein Auflösungslauf unter einer einzigen Mitglieds-Identität meldet erfolgreich
   „DELETE 1" und lässt die Gesundheitsdaten aller anderen liegen. **Ohne Fehler.**

## Entscheidung

### 1. Selbstbedienung des Admins, kein Betreiber-Auftrag

`POST /v1/household/dissolve`, `AdminPrincipal` + CSRF. Der Betreiber-Anstoß („Admin unerreichbar")
ist ein **eigener Slice** und gehört zu 11-S2: er braucht `audit_log.household_id` erstmals gefüllt,
eine Aufbewahrungsregel für die Auftragstabelle und ein Vier-Augen- oder Karenz-Konstrukt — und
löst keinen Art.-17-Fall.

Bestätigung durch **getippten Haushaltsnamen**, nicht `window.confirm`: das ist die schärfste
irreversible Aktion der Anwendung, und ein Wert, den ein Angreifer nicht kennt, macht sie gegen
Clickjacking-Restrisiken unbrauchbar.

**Keine Blocker.** Die Auflösung ist die Operation, die Blocker *auflöst*; symmetrisch welche
einzubauen wäre ein Zirkel.

### 2. Zweistufig — und die zweite Stufe ist ausdrücklich noch nicht gebaut

**Phase 1 (dieser Slice, sofort):** Haushalt getombstonet, alle Mitgliedschaften beendet, alle
Sitzungen widerrufen, Kinder-Konten vorgemerkt, Ökonomie abgewickelt, Zugänge entwertet.
**Phase 2 (11-S1f, offen):** das endgültige Ausräumen der 41 Tabellen nach der Karenz.

Derselbe Schnitt wie bei der Kontolöschung (11-S1c Antrag → 11-S1d Purge), und aus demselben
Grund: der Löschlauf ist die zerstörerischste Operation im System und verdient einen eigenen
Durchgang. `docs/LOESCHKONZEPT.md` führt Phase 2 als offenen Punkt — **nicht** als erledigt.

### 3. Die Admin-Kontinuität wird freigegeben, nicht umgangen

`dissolve_household` liest denselben mit `FOR UPDATE` gesperrten Bestand wie `leave_household` und
`change_role`, ruft `would_leave_no_admin` aber **bewusst nicht**. KONZEPT §5.1 sagt „es existiert
immer ≥ 1 Admin"; die Auflösung ist die einzige Operation, die das legitim beendet. Die Freigabe
gehört in dieselbe gesperrte Transaktion wie die Prüfung, die sie ersetzt — sonst könnte ein
gleichzeitiger Rollenwechsel dazwischenfahren.

### 4. Kinder-Konten enden mit dem Haushalt

Ein Kinder-Konto hat kein Login außerhalb: kein Passwort, keine E-Mail, und `child_login` verlangt
eine **lebende** Mitgliedschaft. Bliebe es stehen, wäre es unerreichbar **und von keinem Löschjob
erfassbar** — der Konto-Purge hängt an `users.deleted_at`, und das kann nur die Person selbst
setzen. Die Auflösung merkt es deshalb mit vor; es läuft danach durch dieselbe Karenz und denselben
Purge wie jedes andere Konto.

Der Tombstone wird unter `scoped_session(household_id=H, user_id=<kind>)` gesetzt: die
`user_visibility`-Policy erlaubt das UPDATE nur auf `id = app.user_id`. Damit stellt die
**Datenbank** sicher, dass hier kein fremdes Konto vorgemerkt wird — nicht bloß dieser Code.

### 5. Ein eigenes Ereignis, weil die Reihenfolge über Mitglieder hinweg zählt

`household.dissolved` (Payload: nur `household_id`) neben den `member.left`-Ereignissen.

Der Grund ist die Ökonomie und subtil: `revert_listing` kreditiert beim Rückabwickeln den
**Verkäufer**. Laufen die Handler mitgliedsweise, kann der Saldo des Verkäufers längst verfallen
sein, wenn das Escrow des Käufers zurückfließt — die Punkte stranden auf einem Konto ohne
Mitgliedschaft. Beim Einzelaustritt ist das unmöglich, bei der Auflösung der Normalfall.

Der Handler am Composition Root macht deshalb **erst alle** Handelspositionen, **dann alle**
Aufgaben, **dann alle** Punkte-Verfälle. Dieselbe Begründung wie `app/member_exit.py`, eine Ebene
höher. `on_member_left` steigt bei getombstonetem Haushalt vor der Ökonomie aus — nicht wegen
Idempotenz (die Operationen sind idempotent), sondern weil zwei Worker sonst `household.dissolved`
und ein `member.left` gleichzeitig ziehen könnten und die Reihenfolge damit verlöre.

Kalender- und Wearables-Handler bleiben an `member.left`: sie sind mitglieds-gescopt, voneinander
unabhängig und reihenfolgefrei.

### 6. Vier Eintrittstüren bekommen einen Guard

`get_active_role` (das Gate für den Haushaltswechsel), `child_login`, `accept_invite` und
`create_household_invite` lesen `households.deleted_at` heute nicht. Die ersten drei sind echte
Wege zurück in einen aufgelösten Haushalt; die vierte ist über den Sitzungs-Widerruf gedeckt und
bekommt den Guard **trotzdem** — eine Sperre, die an einem vorherigen Schritt hängt, ist dieselbe
Fehlerklasse wie eine Kaskade, auf die man sich ungeprüft verlässt.

### 7. Für Phase 2 vorentschieden: die Menge wird abgeleitet, nicht gepflegt

Weil kein FK auf `households.id` zeigt, ist die Vollständigkeit der Tabellenliste eine reine
App-Zusage. Eine handgeschriebene Liste wäre exakt `_RETENTION_TABLES` (BUGLOG 2026-07-31), nur mit
41 statt 3 Einträgen. Phase 2 leitet die Menge deshalb zur Laufzeit aus `information_schema` ab und
die Reihenfolge topologisch aus `pg_constraint`. Gepflegt wird nur die **Klassifizierung** je
Tabelle — das ist eine DSGVO-Entscheidung, keine Schema-Tatsache — und sie fällt **geschlossen
aus**: eine abgeleitete Tabelle ohne Klassifizierung lässt den Lauf scheitern, statt stillschweigend
zu löschen oder stillschweigend zu überspringen.

## Konsequenzen

- **Positiv:** `sole_member` und `only_children` sind keine Sackgassen mehr; Art. 17 ist für jede
  Konstellation gangbar. Kein neuer Schreibpfad für den Betreiber, also bleibt
  `tests/test_ops_isolation.py` **unberührt** — das Abnahmekriterium ist konstruktiv erfüllt statt
  durch Sorgfalt.
- **Negativ:** Ein aufgelöster Haushalt liegt bis Phase 2 als Tombstone in 41 Tabellen. Der Zugang
  ist beendet, die Daten sind es nicht. Die Oberfläche sagt das.
- **Ehrlichkeit:** Die Auflösung ist **nicht rückgängig zu machen**, und KONZEPT Leitplanke 6 wurde
  in derselben Runde entsprechend eingeschränkt (E9: erst Konzept, dann Code). Ein Bestätigungstext,
  der „30 Tage wiederherstellbar" andeutete, wäre eine Lüge — Phase 1 löscht Art.-9-Daten hart und
  lässt Punkte verfallen.

## Alternativen (verworfen)

- **Löschen unter `custode_maint` mit `WHERE household_id = …`.** Bräuchte SELECT+DELETE+Policy auf
  27 weiteren Tabellen und ersetzte eine erzwungene Grenze durch einen Filter, den man vergessen
  kann. ADR-0083 hat dieselbe Frage für den Export andersherum entschieden; bei einer *löschenden*
  Operation wiegt das Argument schwerer.
- **Harte Sofortlöschung ohne Karenz.** Nimmt der Fehlbedienung jede Chance und weicht ohne Not von
  der Kontolöschung ab.
- **Auflösung als Betreiber-Vorgang.** Löst den Art.-17-Fall nicht (der Admin ist ja da) und
  erkauft ihn mit einer Fähigkeit, die die Betreiber-Grenze aufweicht.
