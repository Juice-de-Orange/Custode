# ADR-0086 — Der Haushalts-Purge leitet seine Menge ab und läuft je Mitglied

**Status:** beschlossen · **Datum:** 2026-08-02 · **Slice:** 11-S1f
**Ergänzt:** [ADR-0085](0085-haushaltsaufloesung.md) §7 · [ADR-0084](0084-loeschung-vs-auditierbarkeit.md) · [ADR-0081](0081-wearables-member-scoped-rls-und-oauth.md)

## Kontext

ADR-0085 hat die Auflösung eines Haushalts in zwei Stufen geschnitten: Phase 1 beendet den Zugang
sofort, Phase 2 räumt nach der Karenz aus. Phase 2 ist dieser Slice, und §7 hatte seine Form
vorentschieden. Die Bestandsaufnahme gegen eine frisch migrierte Datenbank (2026-08-02) hat die
Annahmen bestätigt und drei Zahlen ergänzt, die die Umsetzung bestimmen:

- **41 Tabellen** tragen `household_id`. **Kein einziger Fremdschlüssel zeigt auf `households.id`** —
  das Löschen der Haushaltszeile kaskadiert nichts und wird von nichts blockiert. Die Datenbank kann
  eine vergessene Tabelle **nie** melden. Beim Konto-Purge blockiert wenigstens
  `memberships.user_id`; hier gibt es kein solches Netz.
- **9 FK-Kanten** verlaufen zwischen diesen Tabellen. Vier kaskadieren, **fünf stehen auf
  `NO ACTION`** und binden die Reihenfolge auch *innerhalb* einer Transaktion (keiner ist
  `DEFERRABLE`): `task_instances → task_templates → rooms`, `recipe_ingredients → recipes`,
  `shopping_items → shopping_lists`, `redemptions → rewards`.
- Ein **Trockenlauf** als `custode_app` unter gesetztem Scope zeigt: **40 von 42** Zielen (41
  Tabellen + die `households`-Zeile) lassen ein `DELETE` zu. Genau `audit_log` und `consents`
  scheitern mit `42501` — und beide sollen ohnehin bleiben.

## Entscheidung

### 1. Die Menge wird abgeleitet, nicht gepflegt

`kernel/deletion/household.discover_household_tables` fragt zur Laufzeit den Katalog nach allen
Basistabellen mit `household_id`. Eine handgeschriebene Liste wäre exakt `_RETENTION_TABLES`
(BUGLOG 2026-07-31), nur mit 41 statt 3 Einträgen: eine Behauptung über die Datenbank, die niemand
prüft. Gefragt wird `pg_attribute`, **nicht** `Base.metadata` — das ORM ist nicht das Schema, und
genau in dieser Lücke saßen beim Export `tenancy_probe` und `guides.search_tsv` (ADR-0083).

### 2. Gepflegt wird nur die Klassifizierung — und sie fällt geschlossen aus

`app/household_deletion_policy.py` beantwortet je Tabelle: löschen oder behalten, mit Pflicht-
Begründung. Eine abgeleitete Tabelle ohne Einordnung lässt den Lauf mit `UnclassifiedTableError`
scheitern, **bevor** das erste DELETE fällt. Beide möglichen Vermutungen wären falsch: löschen
zerstörte Daten, über die niemand entschieden hat; überspringen ließe personenbezogene Zeilen liegen
und meldete trotzdem Erfolg.

### 3. Die Reihenfolge kommt aus `pg_constraint`, und die Gegenprobe gehört dazu

`order_children_first` sortiert topologisch, bei Gleichstand alphabetisch (eine laufzeitabhängige
Reihenfolge machte jeden Fehlschlag unreproduzierbar). Der Test prüft **beide** Richtungen: die
abgeleitete Reihenfolge läuft durch, und die **umgekehrte** muss mit `23503` scheitern. Ohne die
zweite Hälfte bewiese der grüne Lauf nur, dass zufällig nichts kollidierte.

### 4. Gelöscht wird als `custode_app` unter RLS — das DELETE nennt den Haushalt nicht

Kein `WHERE household_id = …`. Die Policy der Sitzung zieht die Grenze, wie im ganzen übrigen
System. ADR-0085 hatte die Alternative (`custode_maint` mit Filter) bereits verworfen: sie bräuchte
SELECT+DELETE+Policy auf 27 weiteren Tabellen und ersetzte eine erzwungene Grenze durch einen
Filter, den man vergessen kann. Bei einer *löschenden* Operation wiegt das schwerer als beim Export,
wo ADR-0083 dieselbe Frage andersherum entschied.

### 5. Der Durchgang läuft **je Mitglied**, statt die zwei Sonderfälle zu benennen

`wearable_connections` und `wearable_daily` tragen eine *mitglieds*-gescopte Policy (ADR-0081).
Unter der Identität eines einzelnen Mitglieds meldet ein DELETE dort erfolgreich „0 Zeilen" und
lässt die Art.-9-Daten aller anderen liegen — **ohne Fehler**.

Der naheliegende Fix wäre, diese zwei Tabellen zu benennen. Das wäre **eine Repräsentation statt des
Begriffs** — die Fehlerklasse, die diese Codebasis fünfmal bezahlt hat: die Liste veraltet beim
nächsten mitglieds-gescopten Modul, und niemand merkt es, weil ein zu enger Lauf **grün** aussieht.
Stattdessen wiederholt der Purge jede Tabelle unter jeder Mitglieds-Identität. Die Datenbank
entscheidet, was jede Sitzung sehen darf; dieser Code muss es nicht wissen.

Kosten: für haushaltsgescopte Tabellen räumt der erste Durchgang alles ab, die übrigen treffen
0 Zeilen — bei einer Handvoll Mitgliedern ein paar Dutzend wirkungslose Anweisungen.

**Negativprobiert:** wird die Schleife auf ein Mitglied verkürzt, gehen zwei Tests rot — die
generische Vollständigkeitsprüfung und der eigene Art.-9-Fall.

### 6. `points_ledger` wird gelöscht

`CLAUDE.md` nennt den Ledger „append-only". Diese Regel betrifft **Korrekturen im lebenden Ledger**:
eine Buchung wird nie überschrieben, sondern gegengebucht. 11-S1b lässt Restpunkte deshalb als
*Buchung* verfallen statt sie zu löschen — weil jede Buchung zwei Konten hat und ein Löschen die
Salden **anderer** verschöbe. Nach der Auflösung gibt es keine anderen Salden mehr, die stimmen
müssten. Der Ledger ist personenbezogen — über die Kontostrings `member:<uuid>` und `created_by`;
eine `member_id`-Spalte hat er nicht (die liegt auf `redemptions`). Keine Aufbewahrungspflicht steht
dagegen: Punkte sind kein Geld.

### 7. Die `households`-Zeile wird gelöscht, nicht anonymisiert

Ihr Fehlen **ist** die Markierung „ausgeräumt". Es braucht keine zweite Spalte, die dasselbe
behauptet — also **kein `households.purged_at` und keine Migration**. Der Unterschied zur
`users`-Zeile (die anonymisiert stehen bleibt, KONZEPT §5.1) ist kein Widerspruch, sondern folgt aus
derselben Frage: dort halten 27 Verweise ohne Fremdschlüssel die Zeile am Leben, hier zeigt
**nichts** auf sie. `audit_log.household_id` bleibt als nackte Kennung bestehen — ADR-0084 sieht das
ausdrücklich vor, weil sie den Haushalt bezeichnet und nicht die Person.

### 8. Zwei Tabellen bleiben, und beide sind DB-seitig gesperrt

`audit_log` (ADR-0084: pseudonymisieren statt löschen; `custode_app` hat seit Migration 0057 weder
SELECT noch DELETE) und `consents` (Art. 7 Abs. 1 — der Verantwortliche muss nachweisen können, dass
eingewilligt wurde, gerade für die Art.-9-Verarbeitung, die hier gerade endet; `custode_app` darf
nur SELECT und INSERT).

Dass beide *ohnehin* gesperrt sind, ist kein Zufall, sondern der Beleg: die Einordnung „behalten"
ist hier nicht bloß eine Zusage, sondern von der Datenbank gedeckt. Ein eigener Test hält das fest
(`42501` erwartet) — sonst hübe ein späterer Grant die Entscheidung stillschweigend auf.

### 9. Ein Haushalt je Transaktion, ein Cron um 04:00

Zwischen Haushalten gilt alles-oder-nichts **nicht**: einer, der an einer Besonderheit scheitert,
darf die anderen nicht mitreißen (Lehre des Reapers). Innerhalb eines Haushalts schon — ein halb
ausgeräumter Haushalt wäre ein Zustand, den niemand benennen kann, und der nächste Lauf fände ihn
als „fällig" wieder. 04:00 liegt **nach** dem Konto-Purge (03:30): der räumt personenbezogene Zeilen
quer über alle Haushalte, dieser danach den Rest eines beendeten Mandanten.

Fehlschläge gehen als **eigene** Logmeldung nach oben, mit SQLSTATE statt Fehlertext (Postgres hängt
bei Constraint-Verletzungen „Failing row contains (…)" an — das wären Zeilendaten im Log).

## Konsequenzen

- **Positiv:** Art. 17 ist für den Haushalt zu Ende gebaut. Keine Migration, keine neuen Grants,
  kein Betreiber-Handgriff. Die Vollständigkeit ist erzwungen statt dokumentiert: eine neue
  haushaltsgebundene Tabelle macht CI rot, bis jemand entscheidet.
- **Negativ:** Der Lauf skaliert mit `Mitglieder × Tabellen`. Bei einem Haushalt mit 6 Personen sind
  das 234 DELETEs, von denen 195 nichts treffen. Das ist der Preis dafür, die mitglieds-gescopten
  Tabellen nicht zu benennen — und er ist gegenüber einer Liste, die still veraltet, günstig.
- **Ehrlichkeit:** Der Purge ist nicht rückgängig zu machen, und die 30 Tage sind eine
  Purge-Verzögerung, keine Wiederherstellbarkeit (ADR-0085, KONZEPT Leitplanke 6).

## Alternativen (verworfen)

- **Die zwei mitglieds-gescopten Tabellen benennen.** Billiger im Lauf, teurer im Betrieb: die Liste
  veraltet still, und ein zu enger Lauf sieht grün aus. Siehe §5.
- **`households.purged_at` wie bei `users`.** Braucht eine Migration und eine Regel, wann der
  Tombstone selbst endet — Komplexität ohne Nutznießer, solange nichts auf die Zeile zeigt.
- **Löschen unter `custode_maint` mit `WHERE household_id = …`.** Bereits in ADR-0085 verworfen;
  siehe §4.
- **Die Reihenfolge hart im Code.** Fünf `NO ACTION`-Kanten heute, unbekannt viele morgen. Eine
  Liste, die etwas über die Datenbank behauptet, muss gegen die Datenbank geprüft werden — dann kann
  man sie auch gleich aus ihr ableiten.
