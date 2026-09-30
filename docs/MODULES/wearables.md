# Modul `wearables`

**Zweck:** Anbindung von Wearable-Clouds (KONZEPT §5.15). Gesundheitsdaten nach Art. 9 DSGVO —
nur lesend, nur die Typen mit expliziter Einwilligung, mitglieds-privat.

**Stand:** 9-S5 (OAuth-Fundament + Consent + Datenmodell), 9-S6 (Ingest-Cron + Retention),
9-S7 (Scheduling-Naht) und 9-S8 (Web). Der Strang ist damit nutzbar.

**Strikt optional (Leitplanke 7):** Jede abhängige Funktion hat einen gleichwertigen Basis-Pfad
ohne Wearable-Daten — sie verfeinern nur.

## Datenobjekte (Migration 0069)

| Tabelle | Kern |
|---|---|
| `wearable_connections` | `member_id`, `provider ∈ {oura, garmin, healthconnect}`, `tokens_enc?` (ein SecretBox-Wert), `token_expires_at?` (Klartext), `scopes[]`, `status ∈ {active, needs_reauth}`, `last_error?`, `last_sync_at?`. Eindeutig `(household_id, member_id, provider)`. |
| `wearable_daily` | `day`, `sleep_score?`, `sleep_minutes?`, `readiness?`, `steps?`, `active_kcal?`, `rhr?`, `fetched_at`. Eindeutig `(household_id, member_id, provider, day)`. |

Beide mit `CHECK (deleted_at IS NULL)` — Art. 9 verlangt echtes Löschen; kein Papierkorb, keine
Aufnahme in `_RETENTION_TABLES`.

Consent liegt im **geteilten** Ledger `consents` (`accounts`, Migration 0013 + 0068).

## Sicherheit: mitglieds-gescopte RLS (ADR-0081)

Die Policy `member_isolation` prüft `household_id` **und** `member_id`. Das ist die Abweichung
vom Hausmuster: bei `external_calendar_subscriptions` ist owner-only eine Service-Konvention,
hier ist es die Datenbank. Ein Mitbewohner — **auch ein Admin** — liest 0 Zeilen; die Rolle steht
bewusst nicht im Prädikat.

Folge für den Ingest-Cron: Aufzählen unter `custode_maint` (`maint_all` ist **SELECT-only**),
Schreiben immer unter `scoped_session(household_id, user_id=member_id)` — das ist der
Mechanismus, der N-2 auch für einen Hintergrundjob hält, keine Konvention. `ops_readonly` hat
keinen Grant — die Betreiber-Konsole sieht keine Gesundheitsdaten, auch nicht aggregiert.
Einzige Ausnahme: der Retention-Job darf unter `custode_maint` **löschen**, aber nur auf
`wearable_daily` (Migration 0070).

## Ingest + Retention (9-S6)

**Zwei Cron-Jobs**, beide in `app/worker.py`:

| Job | Cron | Verhalten |
|---|---|---|
| `ingest_wearables_job` | `20 4 * * *` | Respektiert den Kill-Switch (`CUSTODE_OURA_ENABLED`) und kehrt aus, bevor irgendetwas aufgezählt wird. |
| `reap_wearable_daily_job` | `40 3 * * *` | **Läuft immer** — Daten müssen altern, auch wenn keine neuen ankommen. |

Reihenfolge je Verbindung — **Rolle → Refresh → Fetch → Consent-Filter**:

1. **Rollen-Nachlauf.** Ein zwischenzeitlich zum Kind herabgestuftes (oder entferntes) Mitglied
   verliert Verbindung **und** Daten. Geprüft **vor** jedem ausgehenden Request, damit eine
   Herabstufung auch den Verkehr stoppt, nicht bloß die Speicherung.
2. **Refresh**, nur wenn der Token binnen 30 min abläuft. Erfolg ersetzt `tokens_enc` komplett
   (Provider rotieren Refresh-Tokens). Ablehnung → `status='needs_reauth'`, und die Verbindung
   wird künftig nicht mehr aufgezählt — kein nächtliches Hämmern.
3. **Fetch** über ein Fenster von `INGEST_WINDOW_DAYS = 3`: Provider finalisieren und korrigieren
   Nächte nachträglich. Upsert auf `(member, provider, day)`.
4. **Consent-Filter** — hier, nicht im OAuth-Scope, wird Consent pro Datentyp tatsächlich
   durchgesetzt (`daily` deckt drei Typen ab). Nicht-zugestimmte Spalten werden auf **NULL**
   gesetzt, nicht ausgelassen: sonst überlebte der Wert eines zwischenzeitlich widerrufenen Typs.

**Retention** hat eine andere Achse als der Papierkorb-Reaper: Alter des **Messtags**, nicht Alter
einer Löschmarkierung (diese Tabellen verbieten Tombstones). Default 90 Tage
(`CUSTODE_WEARABLE_RAW_RETENTION_DAYS`). **Die Retention lässt `wearable_connections` unangetastet
— eine Verbindung ist kein Messwert**, und die Tabelle steht nicht in `_RETENTION_TABLES` (die
Liste ist ihrerseits gegen die Datenbank geprüft).

Seit 11-S1d hat `custode_maint` auf `wearable_connections` trotzdem ein DELETE — nicht für die
Retention, sondern für den **Konto-Purge** (Migration 0072). Die Begründung steht in
`docs/LOESCHKONZEPT.md`: bliebe die Verbindung nach einer Kontolöschung stehen, wäre das ein
zurückgelassener Art.-9-Datensatz. Der `member.left`-Handler räumt sie schon beim Austritt ab, aber
eine endgültige Löschung darf sich nicht darauf verlassen, dass ein früherer Schritt gelaufen ist.
**Unverändert gilt: `custode_maint` darf nicht *schreiben*** — jede inhaltliche Änderung läuft über
die eigene Session des Mitglieds, und `tests/test_wearables_rls.py` prüft das weiterhin.

**Beim Haushalts-Purge (11-S1f, ADR-0086) fallen beide Tabellen ebenfalls** — und dieses Modul ist
der Grund, warum jener Lauf so aussieht, wie er aussieht. Weil die Policy hier auf `member_id`
prädiziert, meldete ein DELETE unter der Identität *eines* Mitglieds erfolgreich „0 Zeilen" und
ließe die Art.-9-Daten aller anderen liegen — **ohne Fehler**. Der Purge wiederholt deshalb seinen
ganzen Durchgang **je Mitglied**, statt diese zwei Tabellen zu benennen. **Folge für dieses Modul:
wer hier eine weitere mitglieds-gescopte Tabelle ergänzt, muss am Purge nichts tun** — genau dafür
gibt es dort keine Liste.

**Fehler-Isolation dreistufig** (wie der CalDAV-Sync): ein unplausibles Feld wird verworfen, eine
kaputte Verbindung bekommt `last_error` und der Lauf geht weiter, ein kaputter Lauf loggt und der
nächste Tick versucht es erneut. Kategorien: `crypto_unconfigured`, `tokens_undecryptable`,
`no_tokens`, `no_refresh_token`, `no_consent`, `refresh_failed`, `token_rejected`.

## Consent pro Datentyp

Vokabular (`types.py`): `wearable_sleep`, `wearable_readiness`, `wearable_activity`,
`wearable_heartrate` — feiner als Ouras Scopes (`daily` deckt drei ab). `scopes_for()` bildet die
Vereinigung; gefiltert wird beim Ingest pro Typ.

- Widerruf = **neue** Ledger-Zeile (`action='revoke'`); wirksamer Stand = Fold „letzte Zeile je
  Typ gewinnt" (`accounts.api.effective_consents`).
- Consent entsteht **im Callback, in derselben Transaktion wie die Verbindung**.
- Widerruf eines Typs nullt sofort dessen Spalten in `wearable_daily`.
- **Invariante:** keine Verbindung ohne mindestens einen aktiven Consent — Widerruf des letzten
  Typs löscht die Verbindung hart.

## Schnittstellen

- **HTTP `GET /v1/wearables/connections` (member/admin):** eigene Verbindungen →
  `list[ConnectionResponse {id, member_id, provider, status, has_tokens, consent_types, scopes,
  last_sync_at?, last_error?}]`. Tokens sind write-only. Kein Flag-Check (Abschalten darf niemanden
  von den eigenen Daten aussperren).
- **HTTP `POST /v1/wearables/oura/authorize` (member/admin, CSRF):** `{consent_types[≥1]}` →
  `{authorize_url}`. Prüft Flag (403), Bestand (409), Crypto-Key + Adapter (503) — alles **vor**
  dem Redirect.
- **HTTP `GET /v1/wearables/oura/callback`:** **unauthentifiziert**, `include_in_schema=False`,
  antwortet **302** nach `<public_base_url>/profile?connected=oura` bzw. `?error=<slug>`.
- **HTTP `PATCH /v1/wearables/connections/{id}/consents` (member/admin, CSRF):** ersetzt die
  Typen; leere Liste ⇒ trennt und antwortet `null`.
- **HTTP `DELETE /v1/wearables/connections/{id}` (member/admin, CSRF):** hart, 204. Funktioniert
  **ohne** Crypto-Key und mit abgeschaltetem Adapter.
- **Zwei Konsumenten:** `scheduling` (Slot-Hinweis `low_recovery`) und `mealplanner`
  (`GET /v1/mealplan/suggestion` — der **nicht schreibende** Vorschlag; der Schreibpfad
  `POST /suggest` bleibt bewusst signalfrei, ADR-0081 §9).
- **Cross-Modul:** importiert nur `kernel/*` + `accounts.api` (`record_consents`,
  `effective_consents`, `get_active_role`, `household_flags`).
  `wearables.api` exportiert die Hintergrund-Einstiege (`ingest_all`, `reap_wearable_daily`) und
  **die Daten-Naht** `recovery_signal(session, member_id, today) -> RecoverySignal(available,
  low_recovery, as_of)` — **ein Boolean, nie ein Score** (ein roher Gesundheitswert über einer
  Modulgrenze *ist* das Gesundheitsdatum). Nur `scheduling` und `mealplanner` dürfen `wearables`
  überhaupt importieren (import-linter), und auch die nur über `api`.
- **Events out:** — **bewusst keine.** Der SSE-Fan-out ist haushaltsweit; ein
  `connection.created`-Hint würde Mitbewohnern verraten, dass jemand ein Wearable verbunden hat
  (N-2). Gilt auch für `wearable.daily_ingested` in 9-S7.

## Web (9-S8)

Die Sektion sitzt auf **`/profile`**, nicht auf einer Haushalts-Seite — die Daten sind
mitglieds-privat, also gehören sie dorthin, wo ein Mensch seine eigenen Dinge verwaltet. Das ist
zugleich das Ziel des Callback-Redirects (`?connected=oura` / `?error=<slug>`).

- **Verbinden:** Consent-Checkboxen pro Datentyp → „Oura verbinden" → **volle Navigation** zum
  Provider (kein Popup: der Callback ist ein server-seitiger Redirect zurück in die App, eine
  Popup-Kette würde das verlieren). Ohne einen einzigen Haken ist der Knopf deaktiviert — eine
  Verbindung ohne Rechtsgrundlage darf gar nicht erst starten.
- **Ändern:** Ein Haken weg → PATCH mit der **vollständigen neuen Menge**, nicht mit einem Delta.
  Der letzte Haken weg trennt (das Backend antwortet `null`, die UI zeigt wieder den Verbinden-
  Zustand). Der Hinweistext sagt beides vorher an.
- **Trennen:** zweistufig mit `danger`-Variante; der Bestätigungstext nennt die Folge
  („endgültig löschen … lässt sich nicht rückgängig machen"), weil es keinen Papierkorb gibt.
- **`needs_reauth`** ist der einzige Status, der den Menschen etwas angeht — er wird in `rost`
  hervorgehoben. Ein `last_error` aus dem Nachtlauf wird ruhig gemeldet („versucht es heute Nacht
  erneut"), nicht als sein Problem.
- **Die UI zeigt nie einen Messwert** — nur *ob* verbunden ist und *welche* Typen zugestimmt sind.
  Ein Test hält das fest, damit kein künftiges Feld still in den DOM rutscht.
- Flag `wearables` aus (Default) → die Sektion erscheint gar nicht; die API lehnt zusätzlich ab.

## AuthZ-Matrix

| Route | anonym | auth (kein HH) | child | guest | member | admin | fremdes **Mitglied** | fremder Haushalt |
|---|---|---|---|---|---|---|---|---|
| `GET /connections` | ✗ (401) | ✗ (403) | ✗ (403) | ✗ (403) | ✓ eigene | ✓ eigene | **RLS: 0 Zeilen** | **RLS** |
| `POST /oura/authorize` | ✗ | ✗ (403) | ✗ (403) | ✗ (403) | ✓ | ✓ | n/a (immer self) | **RLS** |
| `GET /oura/callback` | ✓ (State = Credential) | ✓ | ✗ (`?error=forbidden`) | ✗ | ✓ | ✓ | n/a | n/a |
| `PATCH /connections/{id}/consents` | ✗ | ✗ (403) | ✗ (403) | ✗ (403) | ✓ eigene | ✓ eigene | **404** | **RLS** |
| `DELETE /connections/{id}` | ✗ | ✗ (403) | ✗ (403) | ✗ (403) | ✓ eigene | ✓ eigene | **404** | **RLS** |

Die Spalte „fremdes Mitglied" ist neu und trägt die N-2-Aussage: ein Admin bekommt **dieselbe
404** wie ein Fremder — die Antwort bestätigt nicht einmal, dass die Verbindung existiert.

## Flags & Kill-Switches

- Haushalts-Flag `wearables` (Default **aus**), **server-seitig erzwungen** (403
  `feature_disabled` beim Verbinden). Anders als bei `weather`: bei einem Art.-9-Feature muss
  „aus" heißen, dass die API ablehnt, nicht nur dass eine Kachel fehlt.
- `CUSTODE_OURA_ENABLED` (Betreiber-Kill-Switch) und fehlende Client-Credentials → Null-Adapter,
  der **wirft** → 503 `wearables_disabled`.
- Ohne `CUSTODE_CRYPTO_KEY` → 503 `crypto_unconfigured` beim Verbinden; Lesen/Löschen laufen.

## Betreiber-Handgriff

Oura-OAuth-App registrieren, `CUSTODE_OURA_CLIENT_ID`/`CUSTODE_OURA_CLIENT_SECRET` in die
Deployment-`.env`, Redirect-URI `<public_base_url>/v1/wearables/oura/callback` dort eintragen.
Ohne diese Werte bleibt die Anbindung sichtbar aus. Der Verifikations-Durchgang danach steht
als Protokoll in `docs/MANUAL_TESTS.md`, Abschnitt E.

## Tests

- `test_wearables_rls.py` (Testcontainers) — **der Kern:** Mitglied-gegen-Mitglied auf beiden
  Tabellen, Admin-gegen-Mitglied identisch, `WITH CHECK` mit fremder `member_id`, maint
  SELECT-only, Tombstone-CHECK, Append-only des Ledgers mit `action`.
- `test_wearables_oauth.py` (rein, kein Docker) — Scope-Ableitung, Authorize-URL,
  Redirect-URI-Identität zwischen Authorize und Exchange, Token-Parsing (inkl. Müll-Antworten),
  `tokens.py`-Round-Trip + Manipulation, Null-Adapter, Factory-Matrix, **Property (hypothesis):**
  der Consent-Fold meldet nie einen nie gewährten Typ.
- `test_wearables_client.py` (rein) — Oura-Datenadapter (vier Endpunkte, Bearer, Ein-Tages-Fenster),
  defensives Mapping (Bereichsverletzungen werden **verworfen, nicht geklemmt**), 401/403 →
  `token_rejected`, 404 = fehlender Scope, 5xx → unavailable; plus die Consent-Projektion
  (nur zugestimmte Typen überleben, widerrufene werden genullt).
- `test_wearables_ingest.py` (Testcontainers) — der Lauf gegen echte RLS: Schreiben unter dem
  Owner-Scope, Re-Run aktualisiert statt zu duplizieren, Rollen-Herabstufung löscht alles **ohne
  Fetch**, Refresh-Rotation, abgelehnter Refresh parkt die Verbindung (und sie wird nicht wieder
  aufgezählt), unentschlüsselbare Tokens pausieren, eine kaputte Verbindung stoppt die anderen
  nicht, Retention löscht nach Messtag-Alter und lässt die Verbindung stehen.
- `test_wearables_signal.py` — die Naht: reine Entscheidungsregel (Schwelle, „ein Score genügt",
  veraltete Lesung sagt nichts, Zeile ohne Scores sagt nichts) **plus** der RLS-Beweis gegen echtes
  Postgres: ein Mitbewohner, der Alices `member_id` übergibt, bekommt `available=False`.
- `test_scheduling_engine.py` (erweitert) — `low_recovery` nur ab 90 min, nur am markierten Tag,
  ohne Wearables byte-identische Vorschläge, und der Hinweis **entfernt/sortiert nichts**.
- `web/src/test/wearables-section.test.tsx` (15) — Verbinden-Flow (gesendete Typenmenge,
  Knopf ohne Consent deaktiviert), Consent-PATCH schickt die volle Menge, letzter Haken erlaubt,
  zweistufiges Trennen inkl. Abbrechen, `needs_reauth` vs. ruhiger Betriebsfehler,
  Callback-Codes, Trio — und der Wächter „rendert nie einen Messwert".
- `web/src/test/wearables-errors.test.ts` (5) — Slug- und Callback-Maps, unbekannte Codes
  bekommen trotzdem einen menschlichen Text, und **jede** erzeugbare Id existiert im Katalog
  (ein roher Slug in der UI ist genau das, was der Test verhindert).
- `web/src/test/a11y.test.tsx` — der Consent-Picker ist axe-clean: eine Einwilligung, die ein
  Screenreader nicht vorlesen kann, ist keine Einwilligung.
- `test_wearables_http.py` (Testcontainers + Redis) — Rollen-Guard, State-Single-Use,
  Provider-Ablehnung, fehlgeschlagener Exchange, Rollenwechsel im Callback-Fenster,
  Consent-Widerruf inkl. Spalten-Purge, „letzter Typ ⇒ trennt", harter Delete, beide
  Enhancement-Pfade, und dass weder Token noch Code noch State je in einer Antwort auftauchen.

## Offene Punkte

**Das Oura-Feld-Mapping ist gegen die Live-API unverifiziert** — es entstand aus der dokumentierten
v2-Form, niemand hat es je gegen ein echtes Konto laufen lassen. `_combine` ist defensiv (jedes
Feld unabhängig optional, Bereichsverletzungen verworfen), ein Fehlgriff kostet also einen
fehlenden Wert, nie einen falschen. Korrektur gehört an den ersten echten Lauf
(`docs/MANUAL_TESTS.md`, Abschnitt E), nicht ins Raten.

Web (inkl. `needs_reauth`-Hinweis für den Nutzer) = 9-S8 ·
Aggregate über die 90 Tage hinaus (KONZEPT: „Aggregate länger") noch nicht gebaut · Garmin
(Business-Approval) und Health Connect = Phase 10/13 · Partitionierung von `wearable_daily`
(ARCH §9) nicht aktiviert, der Unique-Index bleibt partitionstauglich.
