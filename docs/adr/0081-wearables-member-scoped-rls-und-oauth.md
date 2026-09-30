# ADR-0081 — Wearables: mitglieds-gescopte RLS für Art.-9-Daten + OAuth-Fundament

**Status:** beschlossen · **Phase:** 9 (9-S5) · **Datum:** 2026-07-26

## Kontext

KONZEPT §5.15 verlangt Oura-Anbindung über OAuth2 (Personal Access Tokens hat Oura im
Dezember 2025 abgeschaltet), Consent **pro Datentyp**, konfigurierbare Retention und einen
Lösch-Button, der wirklich löscht. Die Daten sind Gesundheitsdaten nach Art. 9 DSGVO.

Zwei Dinge waren beim Bau zu entscheiden, weil das Repo für beide bereits eine etablierte
Lösung hat, die hier **nicht** passt.

## Entscheidungen

### 1. Mitglieds-gescopte RLS statt app-seitigem Owner-Filter

Alle bisherigen Fachtabellen tragen `household_isolation` allein auf `household_id`. Owner-only
löst das Repo app-seitig: `ExternalCalendarSubscription` (Migration 0065) hat genau diese Policy,
und der `member_id`-Filter lebt in `calendar/service.py` plus als Konvention in der
Modul-`CLAUDE.md` („Jeder Read filtert `member_id`"). **DB-seitig darf dort jedes
Haushaltsmitglied jede Abo-Zeile lesen** — inklusive `creds_enc`.

Für Gesundheitsdaten ist das zu wenig. Migration 0069 setzt deshalb `member_id` **in die
Policy**:

```sql
USING      (household_id = current_setting('app.household_id', true)::uuid
        AND member_id    = current_setting('app.user_id', true)::uuid)
```

Begründung:

* KONZEPT §5.15 verlangt wörtlich „getrennte Tabellen mit **engem** Zugriff". Haushaltsweit ist
  genau so eng wie eine Einkaufsliste.
* N-2 („Wearable-Daten ↛ andere Mitglieder — auch nicht für Admins") steht bei den bewussten
  Nicht-Verbindungen, derselben Verbindlichkeitsklasse wie „keine negativen Salden". Diese
  Klasse wird im Repo sonst **erzwungen** (Append-only via Grant-Entzug, Property-Tests), nicht
  per Kommentar zugesichert.
* Die Konventions-Lücke hat sich schon zweimal gerächt (`_visible` musste als No-Go dokumentiert
  werden; BUGLOG 2026-07-08). Bei CalDAV kostet eine vergessene WHERE-Klausel einen sichtbaren
  Fremdtermin. Hier wäre sie eine meldepflichtige Verletzung.
* Es ist **kein neuer Mechanismus**: `app.user_id` setzt `kernel/tenancy/session.py` auf jeder
  scoped session, und user-gescopte Policies laufen seit Migration 0005 (`auth_sessions`,
  `login_events`, Passkeys, Recovery-Codes). Neu ist nur, dass erstmals eine **Fachtabelle** sie
  nutzt — genau deshalb dieser ADR (Prinzip E7: zweite Lösung für ein gelöstes Problem).

Die Rolle steht bewusst **nicht** im Prädikat: DB-seitig gibt es keine Admin-Ausnahme. Ein Admin
ist schlicht eine andere `app.user_id` und sieht 0 Zeilen. `test_wearables_rls.py` beweist das
für beide Tabellen, Mitglied gegen Mitglied und Admin gegen Mitglied.

**Kosten, die wir bewusst kaufen:** Der 9-S6-Cron kann nicht unter `custode_maint` schreiben. Er
zählt Verbindungen unter der `maint_all`-Policy (**SELECT-only**) auf und schreibt pro Mitglied
unter `scoped_session(household_id, user_id=member_id)` — genau das tut der CalDAV-Sync bereits.
`DELETE` für den Retention-Job wird erst mit dessen Migration gewährt (Least Privilege pro
Slice). `ops_readonly` bekommt **keinen** Grant: die Betreiber-Grenze kennt keine
Gesundheitsdaten.

### 2. Hartes Löschen statt Tombstone

Beide Tabellen tragen `CHECK (deleted_at IS NULL)`. Der `HouseholdScoped`-Mixin bringt
`deleted_at` mit, aber Art. 9 verlangt Löschen, das löscht — ein nie genutztes Tombstone-Feld
wäre ein Footgun, und der 30-Tage-Papierkorb würde Gesundheitsdaten still weiter aufbewahren.
Der CHECK macht die Regel DB-erzwungen und hält beide Tabellen zugleich aus
`_RETENTION_TABLES` heraus. Der **Consent-Ledger** wird dabei nicht gelöscht: er belegt, dass
Einwilligung bestand und widerrufen wurde — genau das muss auditierbar bleiben.

### 3. Consent-Widerruf als neue Ledger-Zeile (`consents.action`)

Der Ledger aus Migration 0013 kann nur *erteilte* Einwilligungen abbilden. Migration 0068 ergänzt
genau eine Spalte `action ∈ {grant, revoke}` (reiner Expand, Bestandszeilen = `grant`).
Append-only bleibt unangetastet — ein Widerruf ist eine **neue Zeile**, die Grants bleiben
`SELECT, INSERT`. Der wirksame Stand ist deshalb ein Fold („letzte Zeile je Typ gewinnt",
`accounts.effective_consents`), nie ein Spaltenwert.

Verworfen: Widerruf als eigener `type` (`wearable_sleep_revoked`) — String-Semantik durch die
Hintertür, die jeder Leser des Ledgers neu erraten müsste.

Der `id`-Tiebreak im `ORDER BY` ist nicht kosmetisch: zwei Zeilen derselben Transaktion teilen
`created_at` (`now()` ist transaktionsstabil), und uuidv7 ist monoton.

**Eigenes Vokabular, feiner als die Provider-Scopes:** §5.15 verlangt Consent pro *Datentyp*,
Ouras `daily`-Scope deckt aber Schlaf, Readiness und Aktivität gemeinsam ab. Wir fragen die
Vereinigung der nötigen Scopes an und filtern beim Ingest pro Typ (9-S6).

### 4. OAuth-Flow: Backend-Callback, Redis-State, Fail-fast

* **Confidential Client:** Der Betreiber registriert eine App, Client-ID/Secret sind
  Deployment-Settings. Damit ist der klassische Authorization-Code-Flow mit exakt registrierter
  Redirect-URI + `state` ausreichend; PKCE ist für vertrauliche Clients nicht zwingend.
* **Der Callback ist unauthentifiziert** (`include_in_schema=False`) — dasselbe Muster wie der
  ICS-Feed (ADR-0042): ein unratbares Einmal-Secret ist die Credential. Ein Provider-Redirect
  darf nicht auf Cookies bauen, und der Code darf nie durch JS/History laufen.
* **`state` allein genügt nicht (Nachtrag 2026-07-30).** Der ursprüngliche Entwurf band den
  Callback ausschließlich an den state — der authentifiziert aber den **Vorgang**, nicht den
  **Aufrufer**. Ein Angreifer konnte einen eigenen Flow starten und die Authorize-URL an eine
  andere Person schicken; deren Consent landete in seiner Zeile (BUGLOG 2026-07-30). Der Callback
  prüft jetzt zusätzlich per `peek_access_user_id`, dass der Browser dem Initiator gehört — das
  Access-Cookie ist `SameSite=Lax`/`path=/` und kommt bei der Top-Level-Navigation mit. Fehlende
  Session = Ablehnung: ein nicht zuordenbarer Grant darf nicht angenommen werden. Die Begründung
  im alten Docstring („kein authentifizierter Principal auf dieser Route") war schlicht falsch.
* **`state` trägt die ganze Entscheidung** (Mitglied, Haushalt, gewählte Typen) in Redis, nur
  als SHA-256-Hash, TTL 10 min, single-use (Muster `kernel/auth/verification.py`). Der Callback
  vertraut aus der Query nur dem Code.
* **Rollen-Neuprüfung im Callback:** Auf dem Consent-Screen können zehn Minuten vergehen; das
  Konto kann inzwischen zum Kind herabgestuft oder entfernt worden sein. Der Route-Guard greift
  hier nicht (kein Principal), also fragt der Callback `accounts.api.get_active_role` erneut.
* **Antwort ist 302, nie problem+json** — der Aufrufer ist ein Browser. Fehler werden zu
  `?error=<slug>`; weder Code noch State noch Token erscheinen im Redirect-Ziel.
* **Reihenfolge:** `require_secretbox()` läuft **vor** dem Redirect. Ohne Schlüssel könnten wir
  die Tokens im Callback nicht ablegen — der Nutzer hätte dann eine erteilte Freigabe in seinem
  Oura-Konto, die wir still verwerfen. Lieber vorher scheitern.
* **Atomar:** Verbindung und Consent-Zeilen entstehen in **einer** Transaktion. Daten ohne
  dokumentierte Rechtsgrundlage sind genau das, was Art. 9 verbietet.

### 5. Null-Adapter wirft, statt neutral zu schweigen

`NullWearableOAuth` wirft auf allen drei Methoden `wearables_disabled` — auch im reinen
URL-Builder. Der neutrale No-Op eines Autorisierungs-Flusses ist „verweigern", nicht „eine URL
ausgeben, die ins Leere führt"; letzteres hinterließe eine verwaiste Freigabe beim Provider.
Das ist die ADR-0079-Lehre (`NullCaldav` wirft, weil ein „leeres" Ergebnis den Lösch-Diff
auslöste), eine Schicht früher.

### 6. Keine Domain-Events

`kernel/http/stream.py` streamt Invalidierungs-Hints **haushaltsweit**. Ein
`wearables.connection.created` würde jedem Mitbewohner (und jedem Admin) verraten, dass jemand
ein Wearable verbunden hat — genau die Metadaten-Klasse, die N-2 ausschließt. Das Web (9-S8)
invalidiert per Mutation/Focus-Refetch, dem dokumentierten Fallback. **Dieselbe Auflage gilt für
`wearable.daily_ingested` in 9-S7.**

### 7. Feature-Flag serverseitig erzwungen

`wearables` hängt ohnehin an `accounts.api`, also kostet die serverseitige Flag-Prüfung hier
nichts — und bei einem Art.-9-Feature muss „ausgeschaltet" bedeuten, dass die API ablehnt, nicht
bloß dass eine Kachel fehlt. Neue Naht: `accounts.api.household_flags`.

**Lesen und Löschen prüfen das Flag bewusst nicht.** Ein abgeschaltetes Flag darf ein Mitglied
nicht davon abhalten, seine eigenen Gesundheitsdaten zu sehen oder loszuwerden.

### 8. Die Naht nach außen: ein Boolean, kein Score (9-S7)

`wearables.api.recovery_signal(session, *, member_id, today)` gibt `RecoverySignal(available,
low_recovery, as_of)` zurück — **kein** Readiness-Wert. Ein roher Gesundheitswert, der eine
Modulgrenze überquert, *ist* das Gesundheitsdatum; ein Ja/Nein trägt alles, was ein Vorschlag
braucht, und nichts darüber hinaus.

Zwei Einschränkungen, die aus S-14 selbst folgen („ausschließlich auf Basis der eigenen Daten,
**nur für eigene Vorschläge**"):

* **Nur die eigenen Daten.** Die Naht nimmt eine `member_id`, und die mitglieds-gescopte RLS
  liefert für jede andere nichts — die Zusicherung ist erzwungen, nicht versprochen. Ein Test
  belegt genau das (Mitbewohner fragt Alices Signal ab → `available=False`).
* **Nur die eigenen Vorschläge.** Konsumenten dürfen damit formen, was sie diesem Mitglied
  *anbieten*. Sichtbar werden darf es für niemanden sonst.

**Nur `scheduling` und `mealplanner` dürfen `wearables` überhaupt importieren** (import-linter),
und auch die nur über `api` — ein zweiter Kontrakt sperrt `wearables.models/signal/sync/...`
gezielt für beide.

**Zeitliche Ehrlichkeit.** Wearable-Daten beschreiben die *Vergangenheit*, Planung die *Zukunft*.
Nichts, was heute früh gemessen wurde, sagt etwas über nächsten Donnerstag. Die Naht liefert
deshalb genau eine Aussage — „diese Person ist gerade erschöpft" — und nie eine Wochenprognose;
`scheduling` markiert daraufhin **nur heute**. Eine als Feature verkleidete Wochenprognose wäre
eine Lüge.

**„Meiden" heißt markieren, nicht entfernen.** Slots auf einem Erschöpfungstag bekommen den Code
`low_recovery` (nur ab 90 min Dauer — S-14 spricht von XL-Tasks). Die Slot-Menge bleibt
**unverändert**: nichts wird weggelassen oder umsortiert, ein Haushalt ohne Wearables sieht
identische Vorschläge. Optionen still zu verstecken würde sowohl vom Basis-Pfad abweichen als auch
für den Menschen entscheiden.

### 9. Mealplanner-Anbindung: warum nur als reiner Lesepfad

Die Roadmap nennt „Wearable→Scheduling/**Mealplan** (additiv)". Beim Bau zeigte sich, dass der
naheliegende Anschlusspunkt der falsche ist: `mealplanner.suggest_slot` ist **kein** Vorschlag,
sondern ein Schreibpfad — er ruft `set_slot` und emittiert `mealplan.updated`. Das Ergebnis
landet also unmittelbar im **geteilten** Wochenplan des Haushalts.

Damit würde der Gesundheitszustand eines Mitglieds einen Haushalts-Datensatz bestimmen — genau
das, was S-14 mit „nur für eigene Vorschläge" ausschließt. Dazu kommt ein absehbarer Leck-Kanal:
dieses Repo rendert überall Begründungen (`reasons[]`); sobald der Mealplan eine bekäme, stünde
`low_recovery` in einer haushaltsweiten Antwort.

**Nachgeholt (2026-07-27):** genau diese Form gibt es jetzt —
`GET /v1/mealplan/suggestion` schlägt dem Aufrufer ein Rezept vor und **schreibt nichts**; nur
sein eigenes `PUT /slot` ändert etwas Geteiltes. Weil nichts persistiert wird, darf sein eigenes
Recovery-Signal die Reihenfolge formen: bei niedriger Erholung sortiert
`suggest.pick_quickest` nach Aufwand statt nach „am längsten nicht gekocht" — Wiederhol-Sperre
und Wochen-Ausschlüsse bleiben, denn „du bist müde" darf nicht „iss jeden Tag dasselbe" werden.
Rezepte ohne Zeitangabe sortieren **hinten**: unbekannter Aufwand ist kein Beleg für geringen.
`POST /suggest` (der Schreibpfad) bleibt bewusst signalfrei.

## Konsequenzen

* Der Ingest-Cron öffnet pro Verbindung eine mitglieds-gescopte Session; die maint-Rolle darf
  zählen und — seit Migration 0070 — im Retention-Job löschen, sonst nichts.
* `wearables/api.py` exportiert die mitglieds-gescopte Naht (9-S7) und die Hintergrund-Einstiege
  (9-S6) — eigene Werte für eigene Vorschläge, nie für fremde.
* `wearable_daily` ist in 9-S5 leer und wird erst in 9-S6 befüllt — sie entsteht hier, weil der
  RLS-Negativtest seine eigentliche Aussage nur an den Gesundheitsdaten trifft und der
  Lösch-Pfad sie referenzieren muss (Präzedenz: 0065 legte `last_sync_at` an, das bis 9-S3 NULL
  blieb).
* **Konzept-Abweichung additiv aufgelöst:** §5.15 nennt „Schlafdauer **&** -score", der Port
  kannte nur `sleep_score`. `WearableDaily.sleep_minutes` und die Spalte sind ergänzt;
  `UNKNOWN_WEARABLE` bleibt unverändert. Keine KONZEPT-Änderung nötig.
* Die Eindeutigkeit der Verbindung ist `(household_id, member_id, provider)`, nicht
  `(member_id, provider)`: ein Mensch kann in mehreren Haushalten Mitglied sein, und Verbindung
  wie Consent gehören jeweils zum Paar. Ohne `household_id` im Index sähe die RLS-gefilterte
  Duplikatsprüfung nichts, während das INSERT am globalen Index scheiterte — aus einem sauberen
  409 würde eine rohe Unique-Violation (beim Bau aufgefallen, Test deckt es ab).
* **Betreiber-Handgriff:** Oura-OAuth-App registrieren, `CUSTODE_OURA_CLIENT_ID`/`_SECRET` in
  die Deployment-`.env`, Redirect-URI `<public_base_url>/v1/wearables/oura/callback` dort
  eintragen. Ohne diese Werte bleibt die Anbindung sichtbar aus (503). Der
  Verifikations-Durchgang danach ist `MANUAL_TESTS.md` Abschnitt E.
* **Eingelöst in 9-S6/9-S7/9-S8** (derselbe PR-Strang, s. CHANGELOG 2026-07-30): Ingest-Cron
  samt Refresh-Rotation im Betrieb, Retention-Job, Scheduling-/Mealplan-Naht, Web-UI.
* **Offen (bewusst):** PKCE (Schalter geprüft — für vertrauliche Clients nicht nötig) ·
  Garmin/Health Connect (Phase 10/13).
