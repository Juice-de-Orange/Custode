# Pattern-Katalog

> Gleiche Probleme werden gleich gelöst (Prinzip E7). Eine zweite Lösung für ein
> gelöstes Problem braucht einen ADR. Dieser Katalog wächst mit dem Code; in Phase 0
> sind die Felder reserviert und werden bei Erst-Implementierung gefüllt.

## Pagination
Keyset/Cursor (opak, `(updated_at, id)`), nie OFFSET. Helper in `kernel/http`.
→ Detail folgt mit Phase 1.

## Fehlerbehandlung
RFC 9457 `application/problem+json`, stabile `type`-Codes, Referenzcode aus
`request_id`. Katalog: [`errors.md`](errors.md). Clients verzweigen auf `type`,
nie auf Message-Strings.

## Formulare (Web)
react-hook-form + zod-Schemas aus dem OpenAPI-Generator (eine Validierungsquelle) für
komplexe Formulare; einfache Auth-Formulare nutzen kontrollierte Inputs (`components/
field.tsx`, pure & testbar). Optimistic bei Top-Aktionen, Rollback mit verständlicher
Meldung. **Auth-Client/Session:** der generierte `@hey-api`-Client wird auf Cookie-Sessions
konfiguriert (`credentials: include` + CSRF-Interceptor, `auth/client.ts`); Server-State
„wer bin ich?" via TanStack Query auf `/v1/auth/me` (`auth/session.ts`).
**Der stille 401-Replay puffert den Body im *Request*-Interceptor** (11-B2): ein Body ist einmal
lesbar, `fetch` verbraucht ihn, und der Response-Interceptor bekommt dieselbe Instanz — dort wirft
`clone()`. Wer erst beim Wiederholen klont, heilt nur GETs und lässt jede Schreibaktion nach einer
Pause sichtbar fehlschlagen. **Die Kopie muss dort entstehen, wo der Wert noch existiert**, nicht
dort, wo er gebraucht wird. Dazu zwei Regeln aus demselben Slice: Pfad-Ausnahmen vergleichen
**Segmente**, nie Zeichenketten (`includes("/login")` traf auch `/v1/auth/login-events`), und
`EventSource` braucht einen **eigenen** Reconnect — es läuft nicht durch den fetch-Interceptor, und
der Browser gibt bei einer Nicht-2xx-Antwort *endgültig* auf (ein transienter Abbruch dagegen
bleibt ihm überlassen, sonst laufen zwei Kanäle auf denselben Stream).

## Jobs / Hintergrundarbeit
taskiq, benannte Queues (`default/import/external/notify`); Idempotenz über
`processed_events`; Zustell-Garantie via Outbox, nicht über den Broker.

## Domain-Events
Outbox in derselben Transaktion wie die Fachänderung; Envelope `{id:uuid7, type,
version, household_id, occurred_at, payload}`; Handler idempotent; DLQ nach N Fehlversuchen.

## Mandanten-Isolation (RLS)
`household_id` auf jeder Fachzeile; `FORCE ROW LEVEL SECURITY`; `SET LOCAL
app.household_id` pro Request/Job; Negativtest pro Tabelle. Vorlage in
`kernel/db` + `kernel/tenancy`.

## Auth / Sessions (Cookie)
Opaque Cookie-Sessions: kurzlebiges Access-Token in Redis (`kernel/auth/access.py`),
rotierender Refresh in `auth_sessions` mit Reuse-/Theft-Revoke (Familien-Index). Drei
Cookies (Access `/`, Refresh `/v1/auth`, CSRF nicht-httpOnly) zentral in
`kernel/http/cookies.py`; Double-Submit-CSRF in `kernel/http/csrf.py`. Request-Auth über
`get_current_principal` → `set_principal` → RLS-Scope (`kernel/auth/dependencies.py`).
Detail: [ADR-0021](adr/0021-access-token-cookies-csrf.md). **TOTP-2FA** (RFC 6238, stdlib)
in `kernel/auth/totp.py`; `login` nimmt optionalen `totp_code`, sonst 401 `totp_required`
([ADR-0022](adr/0022-totp-2fa.md)). Einmalige **Recovery-Codes** (gehasht, RLS) in
`kernel/auth/recovery.py` als Login-Fallback (`recovery_code`). **Passkeys (WebAuthn)** via
py-webauthn in `kernel/auth/webauthn.py` (rp_id/Origin aus dem Request, Challenge in Redis);
passwortloser Login, Credentials in `auth_passkeys` ([ADR-0023](adr/0023-passkeys-webauthn.md)).

## Ports & Adapter (Graceful Enhancement)
Jede externe Grenze als Port mit echtem Adapter, **Null-Adapter** (neutrale Antwort)
und Fake (Test). Fachcode fragt nie „ist X konfiguriert?".

## Betreiber-Aggregat-Views (security-definer über alle Haushalte)
Die Betreiber-Konsole sieht **nur Aggregate, nie Fachzeilen** (ADR-0015). Umsetzung:
eine **security-definer**-View (Default, kein `security_invoker`), **Owner `custode_maint`**.
`custode_maint` hat `maint_all`-Policies (USING true) auf den gelesenen Tabellen → die View
aggregiert über alle Haushalte, während `ops_readonly` **kein** Fachtabellen-Grant besitzt und
nur `SELECT` auf die View bekommt. Owner-Wechsel umgebungsunabhängig (kurzes, sofort entzogenes
`CREATE ON SCHEMA`), damit es auch in Prod (Owner kein Superuser, FORCE RLS) korrekt aggregiert.
Negativtest: `ops_readonly` liest die View, aber `SELECT` auf die Fachtabelle → `InsufficientPrivilege`.
Beispiele: `usage_counters`/`daily_metrics` (0055), `household_metadata` (0060), `ops_feedback` (0061).
Detail: [ADR-0071](adr/0071-ops-aggregate-views.md).

## Ops-Bearer-Session (getrennt von der Nutzer-Auth)
Die `/ops`-Endpunkte authentifizieren Operatoren über ein **opakes Bearer-Token** in Redis
(`ops_session:<sha256>`, nur Hash gespeichert, TTL via `ops_session_ttl_s`) — **kein Cookie → keine
CSRF-Fläche** (eigene Subdomain). Login = E-Mail + Passwort + **Pflicht-TOTP**, fail-closed +
konstant-zeitig (Dummy-Hash-Verify bei unbekanntem Operator). DB-Zugriff über die `ops_readonly`-
Session (`get_ops_sessionmaker`); Schreibaktionen über `ops_actions`. `kernel/auth`-Primitive
(Passwort/TOTP/Token) werden wiederverwendet. Detail: [ADR-0072](adr/0072-operator-auth-stack.md).

## Append-only-Log per Grant-Entzug
Sicherheits-/Audit-Logs sind **DB-erzwungen append-only**: **keine** Rolle erhält `UPDATE`/`DELETE`
(Korrektur = neue Zeile), nur `INSERT`/`SELECT` für die berechtigten Rollen; die App-Rolle wird per
`REVOKE` ganz ausgesperrt. Stärker als die reine Konvention beim Punkte-Ledger (ADR-0035), passend für
einen Sicherheits-Log. Schreiben über `kernel/audit/record.py::record_audit`. Negativtest:
`UPDATE`/`DELETE` → `InsufficientPrivilege`. Detail: [ADR-0073](adr/0073-audit-log.md).

## Retention-Registry (Hard-Delete getombsteter Zeilen)
Soft-Delete (`deleted_at`) ist umkehrbar (Papierkorb); der **einzige** sanktionierte Hard-Delete ist
der tägliche Retention-Reaper (`kernel/retention/reaper.py`) unter `custode_maint`. Die **Tabellen-
Erlaubnisliste** (`_RETENTION_TABLES`) liegt am **Worker-Composition-Root** (`app/worker.py`) — der
Kernel kennt keine Modul-Tabellen (E2). Tabellennamen gegen ein striktes Identifier-Muster geprüft;
Kind-Zeilen kaskadieren per FK `ON DELETE CASCADE`. Eine Tabelle tritt der Liste bei, sobald sie ein
Soft-Delete + (später) eine Papierkorb-Sicht hat (P8-S3).

## Mitglieds-private Fachdaten (Art. 9) — RLS auf `household_id` **UND** `member_id`
Der Normalfall isoliert nur den Mandanten; „gehört mir" löst das Repo app-seitig (jeder Read filtert
`member_id`, z. B. `ExternalCalendarSubscription`). Für **Gesundheitsdaten** reicht das nicht: N-2
(„Wearable-Daten ↛ andere Mitglieder — auch nicht für Admins") gehört zur DB-erzwungenen Klasse, und
eine vergessene WHERE-Klausel wäre hier eine meldepflichtige Verletzung statt eines sichtbaren
Fremdtermins. Deshalb steht `member_id` **im Policy-Prädikat** (`member_isolation`, Migration 0069) —
kein neuer Mechanismus, `app.user_id` setzt `kernel/tenancy/session.py` ohnehin auf jeder scoped
session (user-gescopte Policies laufen seit 0005 für `auth_sessions`). Die **Rolle steht bewusst
nicht** im Prädikat: es gibt keine Admin-Ausnahme. Preis: Jobs dürfen nicht unter `custode_maint`
schreiben — sie zählen dort read-only auf und schreiben pro Mitglied unter `scoped_session`.
Negativtest ist Mitglied-gegen-Mitglied **und** Admin-gegen-Mitglied, nicht nur Haushalt-gegen-Haushalt.
Detail: [ADR-0081](adr/0081-wearables-member-scoped-rls-und-oauth.md).

## Widerrufbare Einwilligung im Append-only-Ledger
Einwilligung ist kein Boolean-Feld, sondern eine Historie: `consents` bekommt `action ∈ {grant,
revoke}` (Migration 0068) statt einer Zustandsspalte, ein Widerruf ist eine **neue Zeile**, und die
Grants bleiben `SELECT, INSERT`. Der wirksame Stand ist ein Fold („letzte Zeile je Typ gewinnt",
`accounts.api.effective_consents`) mit `ORDER BY type, created_at DESC, id DESC` — der `id`-Tiebreak
ist nötig, weil Zeilen derselben Transaktion identische `created_at` tragen (`now()` ist
transaktionsstabil) und uuidv7 monoton ist. Verworfen: Widerruf als eigener `type`
(`..._revoked`) — String-Semantik durch die Hintertür.

## Unauthentifizierte Route, die die Session trotzdem lesen darf
Ein OAuth-Callback kommt als Top-Level-GET vom Provider — ohne CSRF-Token, ohne `Authorization`,
also **ohne Principal**. Das heißt aber nicht, dass wir nicht wissen, wer den Browser fährt: unser
Access-Cookie ist `SameSite=Lax` mit `path=/` und wird bei genau dieser Navigation mitgeschickt
(ADR-0021). `peek_access_user_id(request)` (`kernel/auth/dependencies.py`) liest es — **ohne** einen
Principal zu binden und **ohne** zu werfen. Warum das nötig ist: ein `state`-Token authentifiziert
den **Flow**, nicht den **Browser**; ohne den Abgleich landen fremde Tokens in der eigenen Zeile
(BUGLOG 2026-07-30). Regeln: fehlende Session zählt als **Nichtübereinstimmung** (ein nicht
zuordenbarer Grant wird nicht angenommen), die Antwort ist für „kein Cookie" und „falsches Cookie"
**dieselbe** (sonst verrät sie, ob ein `state` existierte), und der RLS-Scope kommt weiterhin aus
dem `state`, nicht aus dem Cookie. Der `state` selbst liegt **gehasht** in Redis und wird mit
`GETDEL` geholt — Lesen und Löschen in *einem* Kommando, sonst ist „single-use" bei zwei
gleichzeitigen Callbacks in Wahrheit „zweimal nutzbar".

## Klassifizierungs-Gate (Vollständigkeit erzwingen statt dokumentieren)
Wenn eine Entscheidung **je Tabelle** getroffen werden muss und Schweigen eine stillschweigende
Antwort wäre, gehört sie nicht in eine Doku-Liste, sondern in ein Gate, das über
`Base.metadata.tables` läuft und an allem **Unklassifizierten** scheitert. Erster Nutzer:
`app/export_policy.py` — jede der 53 Tabellen steht entweder in `EXPORTED` (mit
`personal_columns`, falls die Zeile einer Person zuzuordnen ist) oder in `EXCLUDED` **mit
Begründung**; `tests/test_export_policy.py` macht CI rot, sobald eine Migration eine Tabelle
hinzufügt, ohne die Frage zu beantworten. Ohne das Gate hieße Schweigen „nicht exportiert", und
niemandem fällt beim Schreiben einer Migration ein, dass er gerade eine DSGVO-Entscheidung trifft.

**Zwei Nachträge, die diese Codebasis bezahlt hat.** Erstens: **`Base.metadata` ist nicht das
Schema.** Das ORM kennt weniger Tabellen und Spalten als die Datenbank — `tenancy_probe` und
`guides.search_tsv` saßen genau in dieser Lücke. Das *stärkere* Gate fragt den Katalog
(`information_schema` bzw. `pg_attribute`); wo es billig ist, laufen beide nebeneinander
(`test_export_policy.py` schnell, `test_export_schema_gate.py` gegen die echte DB).

**Zweitens: ableiten schlägt pflegen, wenn das Kriterium am Schema ablesbar ist.**
Die Entscheidungsregel steht in `app/kernel/deletion/__init__.py` und unterscheidet die zwei
Purges: der **Konto**-Purge bekommt seine Spaltenliste gepflegt, weil „zeigt auf eine Person"
nicht am Namen abzulesen ist (`author_id`, `cook_id`, `contact_id` …). Der **Haushalts**-Purge
leitet seine Tabellenmenge dagegen zur Laufzeit ab: `household_id` *ist* ablesbar. Gepflegt wird
dann nur noch die **Entscheidung** je gefundenem Element — und sie fällt geschlossen aus.

## Menge ableiten, Reihenfolge ableiten, Entscheidung pflegen
Wenn kein Fremdschlüssel die Vollständigkeit erzwingt, ist jede handgeschriebene Liste eine
Behauptung über die Datenbank, die niemand prüft — die Fehlerklasse von `_RETENTION_TABLES`
(BUGLOG 2026-07-31). Beim Haushalts-Purge zeigt **kein einziger** FK auf `households.id`; eine
Handliste wäre dieselbe Konstruktion mit 41 statt 3 Einträgen gewesen.
Deshalb: **Menge** aus dem Katalog, **Reihenfolge** topologisch aus `pg_constraint` (fünf
`NO ACTION`-Kanten binden sie auch *innerhalb* einer Transaktion), **Entscheidung** aus einer
gepflegten Klassifizierung, die bei Unbekanntem abbricht.
**Zur Reihenfolge gehört die Gegenprobe:** ein Test, der die **umgekehrte** Ordnung ausführt, muss
mit `23503` scheitern. Ohne ihn beweist der grüne Lauf nur, dass zufällig nichts kollidierte.

## Durchgang je Identität statt Sonderliste
Zwei Tabellen tragen eine *mitglieds*-gescopte RLS (ADR-0081): unter der Identität eines Mitglieds
meldet ein `DELETE` dort erfolgreich „0 Zeilen" und lässt fremde Zeilen liegen — **ohne Fehler**.
Der naheliegende Fix wäre, diese Tabellen zu **benennen**. Das ist eine Repräsentation statt des
Begriffs: die Liste veraltet beim nächsten mitglieds-gescopten Modul, und ein zu enger Lauf sieht
**grün** aus.
Stattdessen wiederholt der Lauf **jede** Tabelle unter **jeder** Identität und lässt die Datenbank
entscheiden, was jede Sitzung sehen darf. Die wirkungslosen Wiederholungen sind der Preis dafür,
dass es keine zweite Liste gibt — und der ist bei einer Handvoll Mitgliedern trivial.
Dasselbe Prinzip in der Löschrichtung: **löschen unter RLS statt mit WHERE-Klausel als `maint`**.
Das `DELETE` nennt den Haushalt gar nicht; es gibt keinen Filter, den man vergessen kann, und keine
27 zusätzlichen Grants für die Wartungsrolle (ADR-0086 §4).

## Abwesenheit als Erledigt-Markierung
`users` brauchte ein `purged_at`, weil die Zeile anonymisiert **stehen bleibt** und `deleted_at`
allein nicht zugleich „vorgemerkt" und „erledigt" heißen kann. `households` braucht keines: die
Zeile verschwindet, ihr **Fehlen ist** die Markierung. Eine zweite Spalte, die dasselbe behauptet,
ist eine zweite Wahrheit — und eine gesparte Migration.

## Ein zwischengespeicherter Scope ist ein Hinweis, keine Berechtigung
Jeder Cache, der eine Autorisierung trägt, ist eine Vollmacht, sobald er länger lebt als die
Entscheidung dahinter. Der Refresh-Pfad mintete Haushalt **und Rolle** aus einem Redis-Eintrag,
den die begünstigte Person selbst gesetzt hatte und der 30 Tage hielt (11-S1g). **Der Prüfpunkt:
wer kann den Wert setzen, und wie lange hält er?**
Abgeleitet wird über **dieselbe** Funktion, die der Nachbarpfad benutzt (hier `get_active_role`) —
zwei Fassungen derselben Bedingung laufen auseinander.
**Und die Gegenregel, die derselbe Slice gekostet hat:** ein *fail-closed lesender* Speicher liefert
bei einem Lesefehler dasselbe „nichts" wie bei „kein Eintrag". Wer daraufhin **aufräumt**, macht aus
einer Störung von Sekunden einen dauerhaften Verlust. Geräumt wird nur, wenn die Autorität
**ausdrücklich** ablehnt.
**Rechte-Änderung ≠ Zugangsänderung:** ein Rollenwechsel entwertet die *Tokens* der betroffenen
Person, nicht ihre *Sitzung* — sie bleibt Mitglied. Zwei Funktionen, nicht eine
(`revoke_access_tokens` vs. `revoke_access_family`).

Vier Eigenschaften machen das Muster tragfähig:
* **Fail closed.** Unklassifiziert ist ein Fehler, kein Default — in beide Richtungen (`EXCLUDED`
  ohne tragfähige Begründung zählt ebenfalls als unklassifiziert).
* **Gegen Veralten gesichert.** Ein zweiter Test prüft die Rückrichtung: die Liste darf keine
  Tabelle/Spalte nennen, die es nicht (mehr) gibt. Ein Geister-Eintrag ist sonst ein stiller
  No-Op — die Redaktion einer umbenannten Spalte schützt nichts mehr.
* **Die Heuristik lebt im Test, nicht im Produktivpfad.** Ein absichtlich **zu breites**
  Namensmuster (`hash|secret|token|password|_enc$|…`) zeigt Kandidaten an; jeder Treffer muss
  entweder behandelt oder in einer `_REVIEWED_SAFE`-Freigabe **mit Grund** quittiert werden. So
  rät zur Laufzeit nichts, und ein neuer Fall kostet eine Zeile statt ein Leck.
* **Die Liste liegt am Composition Root** (`app/export_policy.py`, wie `_RETENTION_TABLES` in
  `app/worker.py`) und reist über `app.state` — der Kernel kennt keine Modul-Tabellen (E2,
  ADR-0039).

Zwei Listen, die dasselbe Ding von zwei Seiten beschreiben, werden **aneinandergekoppelt** statt
parallel gepflegt: eine als „nur ein Zeiger, kein Geheimnis" freigegebene Spalte muss exakt in
`ATTACHMENT_COLUMNS` stehen, sonst gilt sie als harmlos, *weil* sie nur zeigt — während dem Zeiger
nie jemand folgt. Detail: [ADR-0083](adr/0083-datenexport-betroffenenrechte.md).

## Erreichbarkeits-Gate an einer Bundle-Grenze (statt „daran denken")
Sobald zwei Entry-Points **verschiedene** Teilmengen derselben Ressource laden, entsteht eine
Fehlerart, die vorher unmöglich war: etwas, das nur in Teilmenge A steht, wird von einem
**geteilten** Baustein benutzt, den auch B rendert. Kein Typfehler, kein Lint-Fund — man sieht es
erst auf dem Bildschirm, und nur in B.

Erster Nutzer: die i18n-Kataloge (`web/src/i18n/`, 2026-08-01). Die Betreiber-Konsole lud alle 820
Schlüssel der Mitglieder-App und benutzt 73; nach der Trennung fiel ihr Initial-Payload von 159,6
auf 135,5 kB. Der Preis dafür ist genau die neue Fehlerart oben.

`web/src/test/i18n-bundle-split.test.ts` prüft deshalb nicht die Kataloge gegeneinander, sondern
**jeden Entry gegen das, was er erreichen kann**: von `main.tsx` bzw. `ops/main.tsx` aus wird der
relative Import-Graph abgelaufen — dieselbe Dateimenge, die der Bundler zusammenpackt — und jeder
darin referenzierte Schlüssel im Katalog *dieses* Entries gesucht.

Drei Eigenschaften, die das Muster tragen:
* **Die Hülle wird berechnet, nicht gepflegt.** Eine handgeschriebene Liste „diese Komponenten
  benutzt Ops" veraltet beim ersten neuen Import — und zwar unbemerkt.
* **Die Gegenrichtung wird mitgeprüft.** Ein Test hält fest, dass die kleinere Teilmenge klein
  *bleibt* (keine fremden Schlüssel, Größenverhältnis). Ohne ihn wächst der Gewinn still zu und das
  Gate misst am Ende nichts mehr — derselbe Grund, aus dem das Bundle-Budget mitgewandert ist.
* **Das Geteilte hat genau eine Quelle** (`locales/shared.*`, in beide hineingespreizt), und ein
  Test prüft, dass beide Kataloge denselben Wert tragen. Eine Kopie driftet beim nächsten Edit
  auseinander, und nur eine Oberfläche ändert sich.

Negativprobe, die dazugehört: einen Schlüssel der einen Teilmenge in einem geteilten Baustein
verwenden — das Gate muss **den Namen des Schlüssels** nennen, nicht nur „irgendwas fehlt".

## Eine Suite, die ihre Infrastruktur überspringen darf, muss daran scheitern
Ein Test, der ohne seine Datenbank `skip` sagt, ist einzeln vernünftig. **Eine ganze Suite, die das
darf, ist ein Gate, das bei Störung „bestanden" meldet** — dieselbe Konstruktion wie ein Job, der
nur bei Wirkung loggt. Am 2026-08-03 meldete `pytest` ohne Docker `563 skipped, 374 passed` und
Exit 0: die komplette RLS-, HTTP- und Export-Abdeckung war weg, die CI grün, der Deploy lief.

Drei Teile, und der dritte ist der, den man vergisst:
* **Der Lauf endet rot**, wenn Tests wegen fehlender Infrastruktur übersprungen wurden
  (`pytest_sessionfinish` in `backend/tests/conftest.py`). Abschaltbar (`CUSTODE_TESTS_ALLOW_SKIPPED_INFRA=1`)
  — als **Entscheidung**, denn ein Default, der fehlende Abdeckung versteckt, ist der Weg, auf dem
  sie verschwunden ist.
* **Der Grund steht im Log** (`-ra` in `addopts`). Mit `-q` allein sah man `s` und keine Ursache;
  ein Skip ohne Grund ist eine Zahl, keine Information.
* **Der Skip trägt eine erkennbare Kennung** (`INFRA_SKIP_PREFIX`), statt dass das Gate auf einen
  Freitext regext, den der nächste Umbau umformuliert.

**Warum das kein Feinschliff ist:** genau dieses Gate fand beim ersten Lauf einen kaputten
Fixture-Umbau, den `except Exception: pytest.skip("Docker/Postgres not available")` sieben Tests
lang als „kein Docker" ausgab. Ein `except`, das jede Ursache auf eine Diagnose abbildet, ist eine
Repräsentation statt eines Begriffs — dieselbe Fehlerklasse wie der Refresh-Merkzettel, nur im Test.

Nebenwirkung derselben Umstellung, und der Grund, warum sie sich mit jedem Slice weiter auszahlt:
**einmal migrieren, dann kopieren.** Die 72 Migrationen liefen 75-mal (6:52 von 7:19 Backend-CI).
Jetzt laufen sie einmal in eine Template-Datenbank, und jedes Testmodul bekommt seine eigene per
`CREATE DATABASE … TEMPLATE` — eine Dateikopie. Die Isolation bleibt: eine eigene Datenbank ist
mindestens so scharf wie ein eigener Container. Detail: `backend/tests/dbfixture.py`.

## Quermodul-Ablauf mit fester Reihenfolge (Composition Root)
Ein Vorgang, der mehrere Module in einer **bestimmten Abfolge** berührt, hat kein Zuhause in einem
Modul: keines darf ein anderes importieren, und wer die Abfolge in eines hineinlegt, macht es
heimlich zum Orchestrator. Solche Abläufe leben als eigene Datei am Composition Root
(`app/member_exit.py`), rufen ausschließlich `modules/<x>/api.py` und hängen an einem Domain-Event
(ADR-0039; ADR-0035 hatte den Fall als „einführbar, wenn ein echter asynchroner Konsument es
braucht" zurückgestellt).
**Die Reihenfolge ist dann der Inhalt der Datei, nicht ihre Verpackung** — und sie gehört in den
Modul-Docstring, mit dem Grund, nicht nur mit der Nummerierung. Beim Austritt: Escrow zuerst
freigeben, dann Aufgaben, dann den Restsaldo verfallen lassen. Umgedreht käme das Escrow nach dem
Verfall an und läge für immer auf einem Konto, das keine Route mehr auflöst. Ein Test, der die
Reihenfolge umdreht, muss rot werden — sonst ist sie nur eine Behauptung.
Mehrere unabhängige Reaktionen auf dasselbe Ereignis (hier zusätzlich `calendar` und `wearables`)
bleiben dagegen **eigene Handler**: sie beeinflussen einander nicht, und eine gemeinsame
Reihenfolge zu erzwingen, wo keine nötig ist, koppelt grundlos.
**Zweiter Nutzer, eine Ebene höher:** `app/household_dissolution.py` (11-S1e). Derselbe Ablauf,
aber über **alle** Mitglieder — erst alle Handelspositionen, dann alle Aufgaben, dann alle
Punkte-Verfälle. Der Grund ist genau die Reihenfolge: `revert_listing` kreditiert den *Verkäufer*,
und liefe die Abwicklung mitgliedsweise, könnte dessen Saldo schon verfallen sein, wenn das Escrow
zurückkommt. Beim Einzelaustritt unmöglich, bei der Auflösung der Normalfall — und ein Beispiel
dafür, dass „dieselbe Reihenfolge" auf einer anderen Ebene ein **anderes** Ereignis braucht.
