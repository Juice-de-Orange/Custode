# ADR-0083 — Datenexport (Art. 15/20): RLS als Mandantengrenze, Klassifizierung am Composition Root

**Status:** beschlossen · **Phase:** 11 · **Datum:** 2026-07-31
**Betrifft:** `kernel/export` (`collect.py`, `archive.py`), `kernel/http/export.py`,
`app/export_policy.py`, `app/main.py`, `web/src/export/` (Sektion auf `/profile`)
**Bezug:** KONZEPT §9 („Betroffenenrechte technisch eingebaut: Daten-Export pro Nutzer und pro
Haushalt, JSON + Anhänge als ZIP"), `KONFIG/Roadmap_to_V0.1.md` Phase 11,
[ADR-0039](0039-module-outbox-handlers-at-composition-root.md) (Composition Root),
[ADR-0067](0067-vault-client-side-encryption.md) (Vault),
[ADR-0073](0073-audit-log.md) (Audit-Log),
[ADR-0081](0081-wearables-member-scoped-rls-und-oauth.md) (mitglieds-gescopte RLS, N-2)

## Kontext

KONZEPT §9 verspricht zwei Exporte: einen **pro Nutzer** (Art. 15 Auskunft, Art. 20
Portabilität) und einen **pro Haushalt**, jeweils als ZIP mit JSON und Anhängen. Der Slice ist in
der Roadmap Phase 11 verortet; vorgezogen wurde er, weil er *lesend* ist und deshalb nichts von
der Löschkaskade abhängt — umgekehrt schon: wer nicht sagen kann, welche Tabelle einen
Personenbezug trägt, kann auch nicht kaskadierend löschen.

Ein Export ist die unangenehmste Leseoperation im ganzen System: er berührt in **einem** Aufruf
jede Tabelle. Jede Zusicherung, die das Repo sonst pro Modul einzeln einhält — Mandantentrennung,
N-2, „Secrets verlassen den Server nie" — muss hier auf einmal halten, und ein Fehler landet
nicht in einer Antwort auf dem Bildschirm, sondern in einer Datei, die der Betroffene weitergibt.

Drei Kräfte wirken gegeneinander:

* **Vollständigkeit.** Ein Export, der still etwas weglässt, behauptet eine Vollständigkeit, die
  er nicht hat. Das ist schlechter als kein Export.
* **Geheimhaltung.** Ein Passwort-Hash, ein CalDAV-Passwort, ein Oura-Token sind entweder gar
  nicht die Daten des Betroffenen (sondern Zugangsdaten zu *fremden* Systemen) oder Werte, deren
  Herausgabe ein noch aktives Konto angreifbar macht.
* **Wachstum.** Das Schema hat heute 53 Tabellen und wächst mit jedem Slice. Was heute stimmt,
  muss auch nach der nächsten Migration stimmen, **ohne** dass jemand daran denkt.

## Entscheidungen

### 1. Die Mandantengrenze ist RLS, nicht eine WHERE-Klausel

`collect_export` läuft auf der **scoped session des Aufrufers** und filtert nirgends nach
`household_id`. Die Statements sind wörtlich `SELECT * FROM <tabelle> ORDER BY 1` — die Grenze
zieht die Datenbank.

Das ist die Umkehrung der naheliegenden Lösung. Ein Massen-Reader mit 42 Tabellen und einer
`WHERE household_id = :h`-Klausel je Tabelle hätte 42 Stellen, an denen eine vergessene Zeile
einen fremden Haushalt in eine Downloaddatei schreibt — und der Fehler wäre in keinem Review
sichtbar, weil 41 Zeilen daneben richtig aussehen. Mit RLS ist die fehlende Klausel kein Risiko,
sondern der Normalfall: was der Aufrufer nicht sehen darf, liefert die Datenbank nicht.

**Für Art. 9 ist das der eigentliche Punkt.** ADR-0081 hat `member_id` in das Policy-Prädikat der
Wearable-Tabellen gesetzt, statt den Filter im Servicecode zu führen. Genau diese Entscheidung
trägt hier: ein **Admin**, der den Haushalt exportiert, bekommt die Gesundheitszeilen seiner
Mitbewohner **nicht** — nicht weil der Export daran gedacht hat, sondern weil die Datenbank sie
ihm verweigert. Wäre N-2 damals eine Konvention in `service.py` geblieben, hätte ein `SELECT *
FROM wearable_daily` sie in genau diesem Slice unbemerkt gebrochen. Der Testfall ist deshalb
bewusst nicht Haushalt-gegen-Haushalt (das hat jede Tabelle ohnehin), sondern
**Admin-gegen-Mitglied**: `test_household_export_withholds_a_co_members_health_data` wird rot,
wenn `member_id` aus Migration 0069 verschwindet, während jeder bestehende RLS-Negativtest grün
bleibt.

Es gibt in diesem Codepfad **keine** maint-Session und keinen Aufruf, der den Scope weitet. Der
Preis: der persönliche Export eines Mitglieds enthält keine Zeile, die dieses Mitglied nicht
ohnehin in der App sehen könnte. Das ist bei Art. 15 kein Verlust, sondern die richtige
Reihenfolge — der Auskunftsanspruch reicht nicht weiter als die eigene Sicht.

Tabellennamen sind nicht bindbar, also werden alle Identifier in `ExportPolicy.__post_init__`
gegen `^[a-z_][a-z0-9_]*$` geprüft (dasselbe Muster wie `kernel/retention/reaper.py`); der einzige
request-abhängige Wert, die `subject_id`, **ist** gebunden.

### 2. Die Klassifizierung liegt am Composition Root — und ist erzwungen vollständig

`kernel/export` kennt **keinen** Tabellennamen. Die Zuordnung steht in `app/export_policy.py` und
erreicht die Route über `app.state`, wie die Ports auch (E2, ADR-0039 — dieselbe Bauform wie
`_RETENTION_TABLES` in `app/worker.py`). Ein Kernel, der `wearable_daily` buchstabiert, wäre eine
Modulgrenzverletzung mit Ansage.

Wichtiger als der Ort ist die **Vollständigkeitspflicht**: jede Tabelle aus `Base.metadata` muss
entweder in `EXPORTED` (mit `personal_columns`, falls die Zeile einer Person zuzuordnen ist) oder
in `EXCLUDED` **mit Begründung** stehen. `tests/test_export_policy.py` läuft über die Metadaten und
scheitert an allem Unklassifizierten. Heute sind das 42 exportierte und 11 ausgeschlossene
Tabellen.

Der Unterschied zu „das dokumentieren wir" ist der ganze Wert: Schweigen bedeutet sonst
„abwesend", und eine neue Tabelle fiele still aus dem Export — niemandem fällt beim Schreiben
einer Migration ein, dass er gerade eine DSGVO-Entscheidung trifft. Vier weitere Gates halten die
Liste am Schema fest, statt sie altern zu lassen: keine Geister-Einträge
(`test_classification_is_not_stale`), keine Tabelle in beiden Listen, keine Ausschluss-„Begründung"
unter 20 Zeichen, und `personal_columns` müssen auf ihrer Tabelle existieren — ein Tippfehler dort
lieferte sonst schweigend einen **leeren** persönlichen Export statt eines Fehlers.

Die drei Ausschlussgründe sind bewusst Kategorien und keine Einzelfälle: **Betreiber-Ebene ist
kein Haushaltsdatum** (`operators`, `ops_banners`, `global_flags`, `audit_log`), **Transport ist
kein Inhalt** (`events_outbox`, `events_dlq`, `processed_events`, `sync_client_ops` — die
Fachzeile selbst liegt bei), **Referenzdaten gehören niemandem** (`ingredients`,
`ingredient_nutrition`).

### 3. Redaktion ist eine Denylist mit CI-Gate, keine Laufzeit-Heuristik

Der naheliegende Reflex wäre ein Filter zur Laufzeit: „Spalten, die `hash`, `secret`, `token`
heißen, werden geschwärzt." Das ist aus zwei Gründen die falsche Stelle.

Erstens **rät** eine Heuristik. `vault_items.ciphertext` enthält kein verräterisches Wort und
*ist* das Nutzerdatum; `auth_passkeys.public_key` heißt nach Geheimnis und ist per Definition
keines; `wearable_connections.token_expires_at` ist ein Zeitstempel. Eine Regel, die diese vier
Fälle richtig trifft, ist keine Regel mehr, sondern eine Liste mit Extraschritt.

Zweitens **schweigt** eine Heuristik im Fehlerfall. Ein neues `..._enc`-Feld, das aus dem Muster
fällt, ginge zur Laufzeit einfach mit — beim ersten echten Export, ohne Warnung.

Gebaut ist deshalb das Gegenteil: `_REDACT` ist eine explizite Tabelle→Spalten-Karte (vier
Gruppen, jede mit eigenem Grund — Authentifikatoren, Sitzungs-/Feed-Geheimnisse,
Fremdsystem-Zugangsdaten, Schlüsselmaterial), und die **Heuristik lebt im Test**, nicht im
Produktivpfad. `_SENSITIVE_NAME` ist dort absichtlich *zu breit* gefasst
(`hash|secret|token|password|_enc$|wrapped|(^|_)code$|(^|_)key$`): jede Spalte in einer
exportierten Tabelle, die darauf passt, muss entweder redigiert sein oder in `_REVIEWED_SAFE`
**mit Begründung** freigegeben werden. Ein falscher Treffer kostet eine Zeile Klassifizierung, ein
verpasster kostet ein Leck. Das Gate fällt geschlossen aus: unklassifiziert ist ein Fehler, kein
Default.

Zwei Kopplungen halten die beiden Listen zusammen. `test_redaction_targets_exist` prüft, dass jede
redigierte Spalte noch existiert — eine Umbenennung machte die Redaktion sonst zum stillen No-Op
und lieferte den Wert aus. Und `test_blob_references_are_actually_collected_as_attachments`
verlangt, dass jede als „Blob-Referenz, kein Geheimnis" durchgewunkene Spalte genau in
`ATTACHMENT_COLUMNS` steht: sonst gälte eine Spalte als harmlos, *weil* sie nur ein Zeiger ist,
während dem Zeiger nie jemand folgt — der Export verschickte Rezeptzeilen ohne Fotos und sagte
nichts dazu.

### 4. Der zurückgehaltene Wert bleibt sichtbar

Redigiert heißt: der Schlüssel bleibt im JSON, der Wert wird `"<redaktiert>"`. Er wird **nicht**
weggelassen.

Ein fehlender Schlüssel wäre eine Aussage — nämlich „so ein Wert existiert bei dir nicht". Für
eine Auskunft nach Art. 15 ist das die falsche Aussage: ob zu einem Konto ein TOTP-Secret, ein
CalDAV-Passwort oder ein Oura-Token gespeichert ist, gehört zur Auskunft; nur der **Wert** gehört
es nicht. Der Marker sagt beides in einem Zug: es gibt ihn, und wir haben ihn behalten. Das
Manifest listet zusätzlich jede zurückgehaltene Spalte als `tabelle.spalte`, und LIESMICH.txt
nennt die vier Gründe im Klartext.

Deshalb prüft `test_own_credentials_are_redacted_not_omitted` ausdrücklich beides: der Schlüssel
ist da **und** der Wert ist der Marker.

### 5. Persönlich ≠ Haushalt: `personal_columns` statt „alles, was mich betrifft"

`TableSpec.personal_columns` nennt die Spalten, die eine Zeile an eine Person binden (`author_id`,
`member_id`, `user_id`, `cook_id`, …). Der persönliche Export wählt daraus
`WHERE <spalte> = :subject OR …`; Tabellen **ohne** solche Spalte fehlen im persönlichen Export
vollständig.

Das ist die ehrliche Lesart von „Daten, die ihn betreffen": eine geteilte Einkaufsliste ist keine
Aussage über denjenigen, der die Milch eingetragen hat. Die Alternative — im persönlichen Export
den halben Haushalt mitliefern, weil man theoretisch beteiligt war — hätte zwei Nachteile
zugleich: sie gäbe dem Betroffenen Daten *anderer* Leute in die Hand und machte die Datei
gleichzeitig unbrauchbar, weil das Eigene darin untergeht.

**Ausgelassen wird trotzdem nichts stillschweigend.** Jede so übersprungene Tabelle landet in
`ExportResult.skipped` mit dem Grund „keine personenbezogene Spalte — nur im Haushalts-Export
enthalten", steht als `skipped_tables` im Manifest und als eigener Abschnitt in LIESMICH.txt. Der
Leser kann „dieser Haushalt hat keine Rezepte" von „Rezepte waren nicht Teil dieses Exports"
unterscheiden — der Unterschied zwischen einer Auskunft und einem Teil-Dump.

Der Haushalts-Export ist deshalb **kein** Obermenge-Superset: er enthält die geteilten Zeilen und
zusätzlich alles, was die RLS dem aufrufenden Admin zeigt — aber eben nicht die mitglieds-privaten
Zeilen der anderen (Punkt 1) und, weil `auth_sessions`, `auth_recovery_codes`, `auth_passkeys` und
`auth_login_events` seit den Migrationen 0005/0009/0010/0011 ein `user_isolation`-Prädikat auf
`app.user_id` tragen, auch dort nur die eigenen.

### 6. Vault: Ciphertext ja, wrappender Schlüssel nein

`vault_items.ciphertext` **wird** exportiert, `vault_key_envelopes.wrapped_key`/`wrap_meta`
**nicht**.

Das folgt direkt aus ADR-0067: der Server sieht den Klartext nie, der Ciphertext ist das
Nutzerdatum. Ihn zurückzuhalten hieße, dem Betroffenen ausgerechnet die Daten vorzuenthalten, die
am eindeutigsten seine sind. Ihn *mit* dem gewrappten Schlüssel herauszugeben hieße dagegen, das
E2E-Versprechen in eine einzige Datei zu packen: Envelope und Ciphertext zusammen sind nur noch
durch die Passphrase getrennt, und eine ZIP-Datei liegt danach in Downloads-Ordnern, Mail-Anhängen
und Cloud-Backups.

Die Portabilität leidet dadurch messbar — der Ciphertext ist außerhalb der App nicht zu öffnen.
Das ist bei einer clientseitig verschlüsselten Ablage aber kein Exportfehler, sondern die
Eigenschaft, für die sie gebaut wurde. LIESMICH.txt sagt genau das in einem Satz, damit niemand
die Datei für kaputt hält.

### 7. Bewusst synchron — mit 64 MiB als benannter Grenze

Der Export wird **im Request** gebaut und als `application/zip` zurückgegeben. Kein taskiq-Job,
kein Artefakt im Blob-Speicher, keine signierte Download-URL.

Das Job-Muster wäre der reflexhafte Bau, und es wäre hier teurer als das Problem: es bräuchte
einen Artefakt-Speicher, eine signierte URL, eine Ablauffrist und einen Aufräum-Job — vier neue
bewegliche Teile, die ausgerechnet den **sensibelsten** Datensatz des Systems bewachen müssten,
und zwar *ruhend in einem Bucket*, wo er länger liegt als eine Antwort lebt. Für die Haushaltsgröße
dieser Anwendung (F&F-Maßstab: wenige tausend Zeilen, Fotos im einstelligen MB-Bereich) ist eine
synchrone Antwort schlicht die kleinere Angriffsfläche.

Damit „klein genug" keine Annahme bleibt, steht sie als Zahl im Code:
`_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024` (64 MiB). Darüber wird der fertig gebaute Puffer
**verworfen** statt ausgeliefert (`export_too_large`, HTTP 413, Hinweis auf den
Betreiber), nicht gestreckt. Die Grenze ist zugleich das Signal: ein Haushalt jenseits davon
braucht die Job-Variante, nicht einen größeren Puffer. Sie ist die dokumentierte Folgeaufgabe,
nicht ein vergessener Fall.

Zwei Nebenbedingungen gehören dazu: die Antwort trägt `Cache-Control: no-store` (kein geteilter
Cache darf eine Kopie behalten), und die Logzeile trägt **nur Zähler** — `scope`, `rows`, `bytes`.
Ein Export berührt jede Tabelle; eine gesprächige Logzeile an dieser Stelle wäre ein eigener
PII-Vorfall. Der Logger wird pro Aufruf geholt statt beim Import gebunden, weil ein
modulweit gecachter structlog-Logger für `capture_logs` unsichtbar ist — ein Versprechen, das
niemand prüfen kann, wäre keins (`test_the_log_line_carries_counts_but_no_content`).

### 8. Das Manifest ist Teil der Antwort, nicht Verzierung

`manifest.json` nennt Umfang, Zeitpunkt, Zeilenzahl je Tabelle, **jede** zurückgehaltene Spalte,
**jede** ausgeschlossene Tabelle samt Grund, die übersprungenen Tabellen und den Zustand der
Anhänge. `LIESMICH.txt` sagt dasselbe in Prosa für den, der die ZIP öffnet und nicht das JSON.
Je Tabelle liegt eine eigene Datei unter `data/` — ein 40-MB-Einzeldokument hilft niemandem.

Drei kleinere Entscheidungen im selben Ordner:

* **Anhänge degradieren, sie scheitern nicht.** Ohne konfigurierten Blob-Speicher (Null-Adapter)
  beschreibt das JSON weiterhin jedes Foto, und das Manifest sagt, dass die Dateien fehlen und
  warum. Den ganzen Export an einem einzigen unlesbaren Blob scheitern zu lassen, wäre der falsche
  Tausch.
* **Kein Pfad stammt aus einer Zeile.** Blob-Keys sind heute servergeneriert, reisen aber durch
  eine DB-Spalte; `safe_entry_name` nimmt nur das letzte Segment, behält daraus nur
  Buchstaben/Ziffern sowie `-`, `_` und `.` und fällt auf `unbenannt` zurück. Eine ZIP, die beim
  Entpacken `../../etc` schreibt, träfe genau den Menschen, dem wir gerade seine Daten geben.
* **Doppelte Einträge werden übersprungen, nicht überschrieben:** zwei Zeilen können denselben
  Blob referenzieren; im Archiv bleibt der erste Eintrag, beide Keys stehen im Manifest.

### 9. Wer darf was

`GET /v1/me/export` steht **jeder** Rolle offen, ausdrücklich auch Kindern: das Betroffenenrecht
gehört der Person, nicht der Rolle. Kinder sind von Wearables und Vault ausgeschlossen — nicht
davon zu erfahren, was über sie gespeichert ist (`test_a_child_may_export_themselves`).

`GET /v1/household/export` ist **admin-only** (`AdminPrincipal`, sonst 403). Diese Datei
beschreibt alle Mitglieder; sie zu ziehen ist eine Haushaltsleitungs-Handlung. Auch sie weitet
nichts: was die RLS dem Admin verwehrt, verwehrt sie auch hier.

### 10. Web: die Sektion steht auf `/profile`, und der Download läuft durch den generierten Client

Beide Knöpfe sitzen in **einer** Sektion auf `/profile` — auch der Haushalts-Export, obwohl die
Haushaltseinstellungen auf `/account` leben. Es ist derselbe Vorgang derselben Person, nur weiter
gefasst; ein Admin soll seine eigenen Betroffenenrechte nicht an zwei Orten suchen. Das
`isAdmin`-Flag entscheidet dort **nur, ob das Angebot ehrlich ist**; durchgesetzt wird die Regel
serverseitig, und der 403 ist trotzdem als Nachricht abgefangen, weil die Rolle zwischen Rendern
und Klick wechseln kann.

Vier Entscheidungen im Datenpfad, die nicht offensichtlich sind:

* **Blob über den generierten Client, nicht über ein rohes `fetch`.** Die Routen antworten
  `application/zip` statt JSON; `client.get({ parseAs: "blob" })` liefert das und behält dabei
  Cookie-Credentials, CSRF-Interceptor und den stillen 401-Refresh (ADR-0021). Ein eigenes `fetch`
  müsste alle drei nachbauen — und der Fehlerpfad käme dann nicht mehr als `ProblemError` an.
* **Mutation, nicht Query.** Eine TanStack-Query würde bei Fokuswechsel refetchen und damit still
  eine **zweite Kopie personenbezogener Daten** in den Download-Ordner legen. Aus demselben Grund
  `retry: false`: ein fehlgeschlagener Export darf den Server nicht unbemerkt ein zweites
  Mehr-MB-Archiv bauen lassen.
* **Der Dateiname wird gefiltert, nicht übernommen.** `filenameFromDisposition` liest die einfache
  **und** die RFC-5987-Form, `safeFilename` wirft Pfadanteile und Steuerzeichen weg, und ohne
  brauchbaren Header baut der Client den Namen selbst — der Name landet im Dateisystem dessen, der
  geklickt hat. Das ist bewusst dieselbe Regel wie `safe_entry_name` serverseitig, auf beiden
  Seiten der Naht. (`custode-export-…` ist dabei der **technische** Projektname; der Marketingname
  erscheint nur über `BRAND_NAME` im Fließtext.)
* **Die Object-URL wird wieder freigegeben** (im nächsten Tick, weil manche Browser den Speichern-
  Vorgang abbrechen, wenn die URL in derselben Task stirbt). Eine lebende Object-URL hält das
  ganze Archiv — also personenbezogene Daten — für die Lebensdauer des Dokuments im Speicher.

Und eine inhaltliche: **die Sektion nennt selbst, was fehlt.** Sie beschreibt nicht nur, was im
Archiv liegt, sondern auch, was bewusst zurückgehalten wird und dass der Tresor verschlüsselt
mitkommt. Eine Oberfläche, die nur Vollständigkeit bewirbt, verspricht etwas, das die Datei nicht
einlöst; das Manifest sagt dasselbe maschinenlesbar. Die drei Zustände sind vollständig
ausgezeichnet (`role="status"` / `role="alert"`, beide Knöpfe während eines Laufs gesperrt) — das
einzige sichtbare Ergebnis eines fertigen Exports ist eine Datei in der Download-Leiste, und die
sieht ein Screenreader-Nutzer nicht.

### Nachtrag nach adversarialer Prüfung: die Voreinstellung war falsch herum

Der Slice ging zunächst davon aus: **Haushalts-Export = alles, was RLS durchlässt.** Eine
adversariale Prüfung mit vier Lupen und je eigenem Widerlegungs-Durchgang hat gezeigt, dass diese
Annahme in diesem Repo nicht trägt — sie bestätigte sieben Preisgaben, jede davon eine
Eigentümer-Grenze, die **app-seitig statt in RLS** gezogen ist:

| Tabelle | Was der Export ausgeliefert hätte | Wo die Grenze wirklich steht |
|---|---|---|
| `calendar_events` | Titel, Ort, Beschreibung **jedes** `personal`-Termins jedes Mitglieds — und weil CalDAV-Spiegel als `personal` angelegt werden, komplette Privatkalender | `_visible` / 404 in `get_event` (ADR-0040), RLS ist rein haushaltsweit (Migration 0032) |
| `external_calendar_subscriptions` | `caldav_url` mit dem Fremdsystem-**Benutzernamen** im Pfad — genau die PII, die `creds_enc` im Ciphertext hält | Service-Filter auf `member_id`; das Modell sagt zu, dass auch ein Admin die Zeile nie sieht |
| `letters` | Briefe im Volltext, in denen der Admin nicht adressiert ist | Empfängerliste `to_ids` |
| `captures` | die persönliche Zuruf-Inbox (Freitext) | Service-Filter |
| `feedback` | Meldungen samt Diagnose-Anhang — ein Kanal, der sich womöglich **gegen den Admin** richtet | Service-Filter |
| `consents` | s. unten | keine — haushaltsweite RLS |
| `points_ledger` | (umgekehrter Fehler) der persönliche Export filterte auf `created_by` und enthielt damit gerade **nicht** die Buchungen, die der Person gutgeschrieben wurden | Konten sind Strings `member:<uuid>` (ADR-0035) |

Die Reparatur ist deshalb keine Liste von Ausnahmen, sondern eine **umgedrehte Voreinstellung**:
`TableSpec.shared` muss ausdrücklich gesetzt werden. Wer eine neue Tabelle aufnimmt, ohne
nachzudenken, bekommt die restriktive Antwort — zu wenig Daten, nie die einer anderen Person. Von
42 Tabellen sind 26 ausdrücklich geteilt, 15 personengebunden, eine (`calendar_events`) über
`shared_when=("layer","household")` zur Hälfte beides: die geteilte Ebene gehört allen, die
persönliche ihrem Owner. Eine Tabelle, die weder geteilt noch personenbezogen ist, wirft beim Bau
der Policy einen Fehler — sie erschiene sonst in **keinem** Export.

Ebenfalls aus der Prüfung: die 64-MB-Grenze prüfte das **fertige** Archiv. Bis dahin lagen Zeilen,
JSON und ZIP gleichzeitig im Speicher — die Absage kostete mehr als die Antwort (gemessen ~500 MB
Spitze für einen Aufruf, der am Ende 413 liefert). Die Grenze greift jetzt beim **Sammeln**
(`ExportTooLarge`, 200 000 Zeilen). Und der Archivbau läuft in einem Thread: JSON-Serialisierung
und Deflate sind CPU-gebunden und hielten in der Ereignisschleife den ganzen Prozess an.

### Nachtrag: `consents` — wenn die bloße Existenz einer Zeile schon etwas aussagt

Die Zusicherung „RLS hält Art.-9-Daten aus dem Haushalts-Export heraus" gilt für die
**Wearable-Tabellen**, deren Policy-Prädikat `member_id` trägt (ADR-0081). Sie gilt **nicht** für
`consents`: dort ist die RLS haushaltsweit (Migration 0013). Die Consent-Typen heißen aber
`wearable_sleep`, `wearable_readiness`, `wearable_activity`, `wearable_heartrate` — die bloße
**Existenz** einer solchen Zeile verrät einem Admin, dass sein Mitbewohner einen Tracker trägt und
welche Werte er teilt.

ADR-0081 §6 hat exakt diese Metadaten-Klasse als Domain-Event abgelehnt: ein
`wearables.connection.created`-Hinweis „würde jedem Mitbewohner (und jedem Admin) verraten, dass
jemand ein Wearable verbunden hat". Ein Export, der dieselbe Aussage in einer ZIP-Datei ausliefert,
unterläuft die Entscheidung durch die Hintertür. Beim Bau zunächst übersehen, beim Nachlesen des
eigenen Codes gefunden.

Deshalb ist `consents` **nicht** als `shared` eingestuft: der Personenfilter greift auch im
Haushalts-Export. der Aufrufer wird deshalb in
*beiden* Umfängen verlangt (ohne seine ID fiele eine solche Tabelle still auf haushaltsweit
zurück — genau die Preisgabe, die das Feld verhindert).

Die Regel zum Weiterdenken: **RLS schützt Zeilen, nicht Aussagen.** Wo der Tabellenname oder ein
Typ-Wert bereits eine Aussage über eine Person ist, reicht Mandantentrennung nicht — dann muss der
Personenbezug in die Abfrage. Negativprobiert: ohne die Markierung liegt die
`wearable_heartrate`-Zeile des Mitbewohners im Admin-Archiv (`test_export_http.py::
test_household_export_hides_a_co_members_health_consent`), mit Gegenprobe, dass sie im
persönlichen Export sehr wohl erscheint.

### Nachtrag: das ORM ist nicht das Schema

Das erste Vollständigkeits-Gate prüfte gegen `Base.metadata` — also gegen das, was die Anwendung
*deklariert*. Der Export liest aber `SELECT *`, und die Datenbank hat mehr:

* **`tenancy_probe`** (Migration 0001) — eine RLS-Sonde mit vollen DML-Grants für `custode_app` und
  ohne ORM-Modell. Für das Gate unsichtbar, also weder exportiert noch bewusst ausgeschlossen.
* **`guides.search_tsv`** — `GENERATED ALWAYS … STORED`; das Modell sagt ausdrücklich „not mapped
  here". Landet trotzdem im Archiv, und das namensbasierte Redaktions-Gate könnte sie nicht einmal
  sehen.

Beides ist inhaltlich harmlos — die Sonde ist leer, der `tsvector` eine Ableitung aus Feldern, die
ohnehin exportiert werden. **Der Befund ist das Loch, nicht der Schaden.** Deshalb gibt es jetzt ein
zweites Gate (`tests/test_export_schema_gate.py`), das aus der Perspektive prüft, die zählt: *was
darf `custode_app` lesen?* Alles, was diese Rolle sehen kann, kann im Export landen. Das schnelle
ORM-Gate bleibt daneben stehen — es läuft ohne Docker und fängt den Normalfall früher.

Dazu eine Textkorrektur, die dieselbe Sorte Fehler war: `LIESMICH.txt` nannte zurückgehaltene
Spalten aus einer Datei, die im persönlichen Export gar nicht existiert (`invites.code`), und trug
über den Ausschlüssen die Überschrift „Ganze Tabellen ohne Personenbezug" — falsch für fünf der
zwölf Einträge, `audit_log` etwa trägt `actor_id`, `target_id` und `household_id`. Die Begründungen
darunter waren richtig; nur die Überschrift behauptete etwas, das die Tabellen nicht hergeben.

## Konsequenzen

* **Positiv:** Die Mandantentrennung des Exports ist dieselbe wie die der App — es gibt keinen
  zweiten, schwächeren Isolationspfad, der auseinanderdriften könnte. Die Art.-9-Zusicherung N-2
  hält ohne Zutun dieses Slices. Neue Tabellen können nicht mehr still aus dem Export fallen.
* **Positiv:** Der Export ist über die Zeit prüfbar: 47 Backend-Tests (15 reine Policy-Gates ohne
  Datenbank, 12 gegen echtes PG 18, 20 über die Routen) und 20 Web-Tests, darunter zwei, die das
  ganze Archiv byteweise nach dem Token eines Mitbewohners durchsuchen — ein künftiger Codepfad,
  der den Wert woandershin kopiert, fiele dort auf.
* **Kosten:** Jede neue Tabelle kostet künftig eine Klassifizierungszeile, sonst ist CI rot. Das
  ist gewollt; es ist derselbe Handel wie beim RLS-Negativtest je Tabelle.
* **Kosten:** Der Export liest 42 Tabellen ohne LIMIT in einem Request. Bei F&F-Größe ist das
  unkritisch, die Obergrenze steht in Punkt 7 — sie ist eine Grenze, kein Puffer.
* **Betrieb:** Es gibt **keinen** neuen Betreiber-Handgriff, keine Migration und keine neue
  Einstellung. Ohne Blob-Speicher funktioniert der Export weiter (ohne Dateien, mit Vermerk).
* **API/Doku:** zwei neue Routen im OpenAPI (`application/zip`, kein JSON-Schema), Clients
  regeneriert; neuer Fehler-Slug `export_too_large` in `docs/errors.md`; Web-Sektion auf
  `/profile` samt DE/EN-Katalog.
* **Getombstete Zeilen sind enthalten.** `SELECT *` filtert `deleted_at` nicht — was im
  Papierkorb liegt, ist gespeichert und gehört damit in eine Auskunft. Erst der Retention-Reaper
  entfernt es endgültig.

## Alternativen (verworfen)

* **`pg_dump` je Haushalt.** Auf den ersten Blick unschlagbar billig — und an drei Stellen falsch.
  Ein Dump läuft mit Owner-/Superuser-Rechten und **umgeht damit genau die RLS**, die hier die
  einzige Mandantengrenze ist; er nähme jede Spalte mit, also auch Passwort-Hashes,
  `creds_enc`, `tokens_enc` und den Vault-Wrapping-Key; und sein Format ist ein
  Postgres-Wiederherstellungspunkt, kein „gängiges, maschinenlesbares Format" im Sinne von Art. 20.
  Zusätzlich kennt ein Dump den Unterschied zwischen persönlichem und Haushalts-Umfang nicht.
* **Ein Exporter je Modul in dessen `api.py`.** Wirkt modulsauber und wäre in der Praxis die
  schlechtere Variante: 20 Implementierungen desselben Musters, jede mit eigener Vorstellung von
  Redaktion und Personenbezug, und **keine** Stelle, die Vollständigkeit prüfen könnte — das
  Metadaten-Gate aus Punkt 2 gibt es nur, weil die Klassifizierung an *einem* Ort liegt. Ein
  vergessener Exporter ist unsichtbar; eine fehlende Zeile in `export_policy.py` ist rotes CI.
  Die Modulgrenze bleibt trotzdem gewahrt: der Kernel kennt keine Tabellennamen, sie kommen vom
  Composition Root (ADR-0039).
* **Allowlist statt Denylist bei der Redaktion** („nur ausdrücklich freigegebene Spalten werden
  exportiert"). Fällt beim *Sicherheits*fehler geschlossen aus — aber beim
  *Vollständigkeits*fehler ebenfalls, und das ist hier der teurere Fehler: eine vergessene
  Freigabe erzeugt eine Auskunft mit stillen Löchern, die niemandem auffällt, während eine
  vergessene Redaktion vom Namens-Gate gefangen wird. Wir haben deshalb **beide** Richtungen
  abgesichert, aber auf unterschiedlichen Ebenen: Allowlist auf **Tabellen**ebene (mit
  Vollständigkeitspflicht), Denylist auf **Spalten**ebene (mit Namens-Gate).
* **Ein einziges `export.json`.** Einfacher zu bauen, unbrauchbar zu lesen — und jeder Betrachter
  müsste das gesamte Dokument in den Speicher nehmen.
* **CSV statt JSON.** Verliert Typen und verschachtelte Felder (JSONB-Spalten wie
  `activation_json`) und bräuchte eine zweite Konvention für Null vs. leerer String.

## Grenzen (bewusst benannt)

* **LIESMICH.txt gibt es nur auf Deutsch.** Es existiert kein Backend-i18n-Laufzeitsystem; die
  Digest-Mails haben dieselbe Grenze. Die strukturellen Namen (`manifest.json`, `data/`,
  `attachments/`) sind englisch und stabil, damit Werkzeuge sich darauf verlassen können. Ein
  englischsprachiges Mitglied bekommt eine vollständige Datei mit deutscher Begleitprosa.
* **`audit_log` ist nicht Teil des Exports.** Es ist ein **Betreiber**-Log, und `custode_app` hat
  darauf seit Migration 0057 kein `SELECT` (ADR-0073); der Ausschlussgrund steht in
  `export_policy.py`.
* **Art. 17 (Löschkaskade) ist nicht Teil dieses Slices.** Phase 11 nennt „Export … & Löschkaskade
  E2E"; erledigt ist der Export. Die Klassifizierung in `export_policy.py` ist allerdings die
  Vorarbeit dafür: sie beantwortet je Tabelle bereits die Frage „hat diese Zeile einen
  Personenbezug, und über welche Spalte?".
* **`personal_columns` ist kuratiert, nicht aus dem Schema abgeleitet.** Es gibt Spalten mit
  Personenbezug, die heute nicht als solche geführt sind — `task_instances.assigned_to`/`done_by`
  und `market_listings.seller_id`/`buyer_id`. Diese Zeilen erscheinen deshalb nur im
  Haushalts-Export, und die Begründung im Manifest („keine personenbezogene Spalte") ist an dieser
  Stelle eine Aussage über die *Klassifizierung*, nicht über das Schema. Der Ausbau ist billig
  (je eine Zeile) und gehört in den Löschkaskaden-Slice, wo dieselbe Frage ohnehin abschließend
  beantwortet werden muss.
* **Der persönliche Export enthält heute keine Anhänge.** Beide Anhangs-Quellen (`recipes`,
  `guide_attachments`) sind haushaltsgeteilte Tabellen ohne `personal_columns`; Dateien liegen
  deshalb nur im Haushalts-Export. Das ist die Folge von Punkt 5 und nicht separat entschieden —
  wer prüft, ob Anhänge mitkommen, muss `GET /v1/household/export` ziehen
  (`docs/MANUAL_TESTS.md`, Abschnitt A).
* **Das Archiv läuft durch den Speicher des Browsers.** Der Client hält es als Blob, bevor es auf
  die Platte geht; auf einem schwachen Telefon ist das bei einem großen Haushalt spürbar. Die
  64-MiB-Grenze deckt den Fall mit ab, aber sie ist serverseitig gewählt und nicht am Gerät
  gemessen. Der Aufruf über die Adresszeile bleibt als Umgehung möglich (GET, Cookie-Session,
  kein CSRF-Token nötig) — das ist der Weg, wenn der Blob-Download je klemmt.
* **Keine Ratenbegrenzung.** Der Aufruf liest 42 Tabellen und ist damit ein billiger Weg, Last zu
  erzeugen — und ein API-weites Ratenlimit, das KONZEPT §10 vorsieht, gibt es im Code bislang
  nicht (ratenlimitiert ist nur der PIN-Login). Bei angemeldeten Aufrufern im F&F-Rahmen ist das
  hinnehmbar; spätestens mit der offenen Beta braucht diese Route ein eigenes, enges Limit. Der
  ASVS-L2-Durchgang derselben Phase ist der richtige Ort dafür.
