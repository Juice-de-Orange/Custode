# Modul `calendar`

**Status:** in Arbeit · **Phase:** 5 · **KONZEPT:** §5.11

## Zweck & Verantwortung
Persönlicher + Haushaltskalender (KONZEPT §5.11). P5-S1 = Event-CRUD mit Layer-System
(`household`/`personal`) als Fundament; RRULE-Serien, ICS-Im/Export und die Scheduling-Engine
(Arbeitszeiten · Routinen · Wetter · Fairness) bauen in späteren Slices darauf auf.

## Datenobjekte (Migrationen 0032 + 0033 + 0034 + 0065 + 0066 + 0067)
| Tabelle | Schlüssel/Invarianten | RLS |
|---|---|---|
| `calendar_events` | id; `owner_id` (Ersteller); `title`; `description?`; `location?`; `starts_at`/`ends_at` (CHECK `ends_at >= starts_at`); `all_day`; `layer ∈ {household, personal}`; `busy` („belegt"-Signal); `rrule?` (RFC-5545, 0033); `kind ∈ {normal, absence, guest}` (0035); `exdates timestamptz[]` (abgesagte Einzeltermine, 0036); `source_uid?` (ICS-Import-Dedup 0037 bzw. VEVENT-UID des Spiegels); `tzid` (IANA-Zone für DST-korrekte Serien, 0039); `overrides jsonb` (verschobene Einzeltermine, 0040); `subscription_id?` (0066: Spiegel-Herkunft, FK ON DELETE CASCADE; partieller Unique `(subscription_id, source_uid) WHERE deleted_at IS NULL`); `ext_href?`/`ext_etag?` (0067: Write-back-Anker, nur Spiegel; der Sync stempelt beide jeden Lauf) | `household_id = app.household_id` (USING + WITH CHECK) |
| `calendar_feeds` (0034) | id; `member_id`; `token` (unique, Secret) | `household_isolation` (USING+WITH CHECK) **+ `maint_all`-SELECT** (cross-household Token-Lookup) |
| `external_calendar_subscriptions` (0065+0066) | id; `member_id` (Owner); `label`; `caldav_url` (≤ 2000, http/https, keine Userinfo); `creds_enc?` (**ein** SecretBox-Wert `v1:<fernet>` über `{username, password}`, ADR-0077; NULL = anonym); `enabled` (Pause ohne Löschen); `last_sync_at?` (letzter **Erfolg**); `last_sync_error?` (Kategorie-Slug, nie URL/Inhalt; NULL = ok); partieller Unique `(member_id, caldav_url) WHERE deleted_at IS NULL` | `household_isolation` (USING+WITH CHECK) **+ `maint_all`-SELECT** (Cron-Enumeration) |

## Wiederkehrende Events (P5-S2, RRULE, ADR-0041)
`rrule` (z. B. `FREQ=WEEKLY;BYDAY=MO`) macht ein Event zur **Serie**; die gespeicherten
`starts_at`/`ends_at` sind die **erste** Occurrence + Dauer. Beim Lesen expandiert `calendar/expand.py`
(rein, ohne DB, DST-sicher via `python-dateutil`) die konkreten Termine **gefenstert** + **gedeckelt**
(`MAX_OCCURRENCES`); ohne `to` gilt ein 90-Tage-Horizont. Ungültige Regel → 422. `EventResponse` trägt
`series_id`/`rrule`/`recurring`; Edit/Delete per `id`/`series_id` betrifft die **ganze Serie**
(Einzel-Occurrence-Ausnahmen/EXDATE = späterer Slice).

RLS-Negativtest (`test_calendar_rls.py`: A↛B→0, WITH CHECK).

## DST-Korrektheit (P5-S9, ADR-0047)
Jedes Event trägt `tzid` (IANA-Zone, Default `UTC`, Migration 0039). Eine Serie wird **in ihrer Zone**
expandiert (`expand.py` ankert `dtstart` via `astimezone(ZoneInfo(tzid))`), sodass „Montag 09:00 Wien"
über die Sommer-/Winterzeit-Umstellung um 09:00 Ortszeit bleibt (nur der UTC-Offset wandert: 08:00Z ↔
07:00Z). Das Web sendet beim Anlegen die Browser-Zone; ungültige Zone → 422; bei der Expansion fällt
eine kaputte Zone defensiv auf UTC zurück. Beweis: **DST-Testsuite** `test_calendar_dst.py` (Frühling +
Herbst, Wall-clock-Stabilität, Kontrast zu `tzid="UTC"`). Der **ICS-Feed** ist seit P9 ebenfalls
DST-korrekt: Events mit echter `tzid` gehen als `DTSTART;TZID=` mit einer `VTIMEZONE` je genutzter
Zone raus (`vtimezone.py`, ADR-0082), Ganztags als `VALUE=DATE`; UTC-Events sind byte-gleich.

## Einzel-Occurrence-Ausnahmen (P5-S5, EXDATE, ADR-0043)
Eine einzelne Serien-Instanz absagen, ohne die ganze Serie anzufassen: `calendar_events.exdates`
(`timestamptz[]`, Migration 0036) hält die **Original-Startinstants** der abgesagten Termine
(RFC-5545 EXDATE). `expand.py` filtert sie **instant-genau** (UTC-normalisiert, DST-sicher) aus den
Occurrences; der ICS-Feed gibt sie als `EXDATE`-Zeile mit, damit Abonnenten sie ebenfalls droppen.
Der Schreibpfad ist **Mengen-Semantik** (idempotent + kommutativ) und läuft daher **ohne If-Match**
über dedizierte Action-Endpoints: `POST /events/{id}/cancel-occurrence` (absagen) und
`restore-occurrence` (zurücknehmen). `occurrence_start` muss eine echte Occurrence der Regel sein
(`is_occurrence`, sonst 422); EXDATE auf eine Nicht-Serie → 422; owner-only (403). Das **Verschieben**
einer Einzel-Occurrence (RECURRENCE-ID-Override) ist ein eigener späterer Slice. `EventResponse` trägt
`exdates`.

## Einzel-Occurrence verschieben (P5-S10, ADR-0048)
`calendar_events.overrides` (jsonb, Migration 0040) bildet verschobene Einzeltermine ab
(`{original_start_iso: {starts_at, ends_at}}`) — analog zu `exdates`, kompakt in der Master-Zeile statt
als eigene Override-Zeile. `expand.py` ersetzt die rule-generierte Occurrence durch den Override und
liefert nun `(original_start, start, end)`; `EventResponse` trägt zusätzlich `original_start` (der
stabile Cancel/Move-Schlüssel). Schreibpfad wie EXDATE (ADR-0043): `POST /events/{id}/move-occurrence`
(verschieben) / `reset-occurrence` (zurücksetzen), owner-only, **kein** If-Match; 422 wenn keine echte
Occurrence / abgesagt / Bereich invertiert. Der ICS-Feed emittiert pro Override ein VEVENT mit
`RECURRENCE-ID`, sodass Abonnenten die Verschiebung übernehmen.

## Layer-Sichtbarkeit (ADR-0040)
RLS isoliert nur den Haushalt. Die `personal`/`household`-Trennung läuft **query-seitig**
(`service._visible`: `layer='household' OR owner_id = caller`). Fremder `personal`-Termin → **404**
(Existenz wird nicht verraten). Schreiben/Löschen ist **owner-only** (403 sonst).

## Schreibpfad
- **PATCH + If-Match** (ADR-0034): `version` = ETag; 412 stale, 428 fehlend. POST/GET liefern ETag.

## ICS-Abo-Feed (P5-S3, Secret-URL, ADR-0042)
Pro Mitglied ein `calendar_feeds`-Eintrag (Migration 0034) mit hochentropem `token`.
`GET /v1/calendar/feed/<token>.ics` liefert die sichtbaren Termine als iCalendar — **unauthentifiziert**
(der Token ist die einzige Credential). Cross-Household-Auflösung via **maint-Session**
(`maint_all`-SELECT-Policy); die Events werden danach **unter dem Owner-Scope** gelesen (RLS +
`_visible`). Wiederkehrende Events als ein VEVENT mit `RRULE` (Client expandiert). `render_ics`
(`calendar/ics.py`) ist rein + ohne DB testbar; RFC-5545-Escaping. `POST /v1/calendar/feed`
erzeugt/rotiert, `DELETE` widerruft.

## ICS-Import (P5-S6, Datei-Upload, ADR-0044)
`POST /v1/calendar/import` nimmt **rohen iCalendar-Text** (`{content, layer}`, größenbegrenzt) und legt
jeden VEVENT als Termin des Aufrufers im gewählten Layer an. **Kein serverseitiger URL-Fetch** → keine
**SSRF**-Fläche (das Webcal-**Abo** mit Pull/SSRF-Guard ist ein späterer Slice). `calendar/ics_parse.py`
ist rein/ohne DB (Spiegel des `ics.py`-Renderers) und deckt den gängigen Export-Subset ab: UTC (`Z`) und
`TZID=` (zoneinfo, unbekannte Zone → UTC), `VALUE=DATE` (ganztägig), `RRULE`, `EXDATE`, Zeilen-Faltung,
TEXT-Escaping; ein VEVENT ohne DTSTART wird übersprungen. Dedup über `calendar_events.source_uid`
(Migration 0037) → erneuter Import derselben Datei ist **idempotent**. Rückgabe `IcsImportResult`
`{imported, skipped, failed}` (`skipped` = UID schon im Haushalt, `failed` = ungültige RRULE).

## Externe CalDAV-Abos (P9-S2, KONZEPT §6 Stufe 3 + §10)
CRUD für Abos externer CalDAV-Kollektionen (Nextcloud/iCloud; Google = OAuth-Folge-Slice) unter
`/v1/calendar/subscriptions`. **Owner-only:** Abos sind persönlich (fremde URLs + Credentials) —
jeder Read filtert `member_id`, ein fremdes Abo (auch für Admins) antwortet **404** (wie ein fremder
`personal`-Termin, ADR-0040-Idee). **Write-only-Credentials (ADR-0077):** `username`+`password`
werden im Service zu **einem** SecretBox-Wert (`v1:`-Präfix) über das JSON `{username, password}`
verschlüsselt (der Username ist PII und bleibt im Ciphertext); keine Response/kein Log/kein
Event-Payload trägt je das Secret — die Wire-Shape hat nur `has_credentials`. `creds.py`
(`encode_credentials`/`decode_credentials`) ist der Format-Kontrakt für den 9-S3-Sync-Worker.
**Graceful Enhancement:** ohne `CUSTODE_CRYPTO_KEY` funktionieren anonyme Abos + alle Reads/Deletes/
credential-freien Patches; nur Writes **mit** Credentials antworten 503 (`require_secretbox`).
**Validierung zur Save-Zeit nur Form** (http/https, Host, keine Userinfo in der URL, ≤ 2000):
bewusst **kein** Private-IP-/SSRF-Check beim Speichern (DNS zur Save-Zeit ist TOCTOU-unsicher,
Rebinding) — der Guard gehört an die Fetch-Zeit und kommt mit dem 9-S3-Pull (`kernel/fetch`-Muster).
Duplikat (aktives Abo, gleiche URL) → **409** `subscription_exists`; Soft-Delete + partieller
Unique-Index erlauben Re-Abo. `enabled` pausiert ohne Löschen (der 9-S3-Cron filtert darauf).

## Pull-Sync (P9-S3, ADR-0079)
15-min-Worker-Cron (`5,20,35,50`, weicht den Reapern aus): Enumeration aller aktiven Abos unter
**maint** (`deleted_at IS NULL AND enabled` — BUGLOG-Checkliste), dann pro Abo **ein**
`REPORT calendar-query` über `kernel/fetch.safe_request` (SSRF-Guard; mit Credentials sind
Redirects origin-gelockt; Multistatus via defusedxml) und Diff/Writes unter der
**`scoped_session` des Abonnenten** (RLS; `maint_all` ist SELECT-only). Spiegel-Events =
`calendar_events` mit `subscription_id`, `layer='personal'`, `busy = NOT TRANSP:TRANSPARENT`,
`tzid` erhalten (ADR-0047); `STATUS:CANCELLED`/remote gelöscht → Soft-Delete;
RECURRENCE-ID-Overrides werden ignoriert (Master gewinnt, dokumentierte Lücke). Unsubscribe
tombstoned die Spiegel in derselben Transaktion. Fehler-Isolation pro Event/Abo/Lauf;
`last_sync_error`-Kategorien s. ADR-0079. Kill-Switch `CUSTODE_CALDAV_SYNC_ENABLED`;
`CUSTODE_CALDAV_ALLOW_PRIVATE_URLS` nur für Dev/Tests/Self-Hosted. Der Port **wirft** bei
Fehlern (`[]` = leere Kollektion — sonst Massen-Tombstone); auch `NullCaldav` wirft
(`sync_disabled`). Reaper purgt `external_calendar_subscriptions` + `calendar_events` (30 Tage).

## Write-back (P9-S4, ADR-0080)
Der Sync ist zwei-Wege — synchron, **remote-first** (lokal ändert sich erst nach Remote-Erfolg;
Tx-Rollback bei jedem Fehlschlag; der Request-Pfad bekommt den Port via `app.state.caldav` +
`get_caldav`-Dependency, Mail-Muster):
- **Create:** `EventCreate.subscription_id` → `render_single_vevent` (Caller-UID, `VALUE=DATE`,
  `TRANSP`, kein METHOD) → PUT `If-None-Match: *` → Spiegel-Row mit `ext_href`/`ext_etag`.
  `layer` wird still `personal`; `kind≠normal` → 422 `external_kind_unsupported`,
  `tzid≠UTC` → 422 `external_tzid_unsupported` (nicht round-trip-fähig).
- **Edit (GET-modify-PUT):** Ressource frisch holen → `patch_vevent` ersetzt NUR die geänderten
  Property-Zeilen (fremde VALARM/ATTENDEE/X-Props bleiben byte-identisch; tzid-Serien in
  `;TZID=`-Lokalform) → PUT mit dem **frischen** GET-ETag. `layer`/`kind`/`tzid`-Änderung →
  422 `external_field_readonly`. Leerer Diff = kein Remote-Call.
- **Delete:** DELETE mit dem gespeicherten `ext_etag` (NULL → unconditional); remote schon weg
  = Erfolg.
- **Fehler:** Remote-Konflikt (412/409; beim Edit auch 404) → **409 `external_conflict`** —
  der nächste Sync-Tick ist die Reconciliation. Kill-Switch → **503 `caldav_disabled`**;
  Credentials ohne Server-Key → **503 `crypto_unconfigured`**; Rest → **502
  `caldav_write_failed`** (+`extra.category`). Fehlende Anker (9-S3-Altzeilen) → 409
  `external_not_synced`, heilen mit dem nächsten Sync-Lauf.
- **Occurrence-Aktionen auf Spiegeln bleiben 409** `external_event_read_only` (Overrides nicht
  gespiegelt). `enabled=false` pausiert nur den Pull — Write-through läuft weiter.
- **Sicherheit:** hrefs nur als server-absolute Pfade (`_target`-Guard — absoluter href würde
  via `urljoin` Credentials zu fremdem Origin tragen); `safe_request` liefert Response-Header
  (PUT-ETag), Header werden nie geloggt.

## Schnittstellen
- **HTTP `/v1/calendar/import` (member/admin, CSRF):** `POST {content, layer}` → `IcsImportResult`.
- **HTTP `/v1/calendar/events` (member/admin, Kinder ✗ in S1):** `GET ?from=&to=` (sichtbare Events,
  optional Zeitfenster — Overlap `starts_at<=to AND ends_at>=from`) · `POST` · `GET {id}` (+ETag) ·
  `PATCH {id}` (If-Match, owner-only) · `DELETE {id}` (Soft-Delete, owner-only) ·
  `POST {id}/cancel-occurrence` · `POST {id}/restore-occurrence` (absagen/zurücknehmen) ·
  `POST {id}/move-occurrence` · `POST {id}/reset-occurrence` (verschieben/zurücksetzen) — alle
  owner-only, **kein** If-Match (Mengen-Semantik, ADR-0043/0048). CSRF auf Writes.
- **HTTP `/v1/calendar/feed` (member/admin, CSRF):** `POST` (erzeugt/rotiert die Abo-URL) · `DELETE`
  (widerruft). **`GET /v1/calendar/feed/<token>.ics` (unauth, read-only)** — der Abo-Endpoint.
- **Cross-Modul:** importiert **nur** `kernel/*`. `calendar.api` exportiert `list_absences(frm, to)`
  (haushaltsweite `kind='absence'`-Events, P5-S4) — der einseitige Einstieg für die spätere
  Scheduling-/Fairness-Logik (Abwesenheit herausrechnen). Kein Modul importiert calendar bidirektional.
- **HTTP `/v1/calendar/subscriptions` (member/admin, Kinder ✗, CSRF auf Writes, P9-S2):**
  `GET` (nur eigene) · `POST` (201+ETag; 409 Duplikat; 503 mit Credentials ohne Key) · `GET {id}`
  (+ETag) · `PATCH {id}` (If-Match; Credentials ersetzen/`clear_credentials`) · `DELETE {id}`
  (Soft-Delete) — alle owner-only (fremd → 404).
- **HTTP `POST /v1/calendar/subscriptions/{id}/check` (member/admin, CSRF, owner-only, P9):**
  einmalige Probe gegen die gespeicherte URL + Credentials → `{ok, category?, objects?}`.
  **Reine Probe:** schreibt nichts — keine Spiegel, kein `last_sync_at`, nicht einmal
  `last_sync_error`; ein „Check", der Zustand ändert, wäre ein zweiter, halbherziger Sync-Pfad.
  Fehler kommen als **Daten** (`ok=false` + Kategorie aus derselben Slug-Familie wie
  `last_sync_error`), nicht als Exception: ein Tippfehler ist das erwartete Ergebnis, kein
  Serverfehler. Ersetzt beim Einrichten das Warten auf den 15-Minuten-Cron. `objects` ist ein
  reiner Zähler (nie Titel/Inhalte).
- **Events out:** `calendar.event.created`/`updated`/`deleted`,
  `calendar.subscription.created`/`updated`/`deleted` → SSE-Entity `"calendar"` (der Sync
  emittiert **ein** `calendar.event.updated` pro geändertem Haushalt).
- **Worker-Naht:** `calendar.api.sync_all_subscriptions(caldav=…, now=…)` — nur vom
  Composition-Root (worker.py) aufgerufen, Port via `app/caldav_factory.py` injiziert.

## AuthZ-Matrix
| Route | anonym | auth (kein HH) | member/admin | child | fremder Haushalt |
|---|---|---|---|---|---|
| `GET /events`, `GET /events/{id}` | ✗ (401) | ✗ (403) | ✓ (eigene+household) | ✗ | RLS: nur eigene |
| `POST` / `PATCH` / `DELETE` | ✗ | ✗ (403) | ✓ (PATCH/DELETE owner-only) | ✗ | **404/RLS** |
| `GET/POST /subscriptions`, `GET/PATCH/DELETE /subscriptions/{id}` | ✗ (401) | ✗ (403) | ✓ (**nur eigene**; fremdes Abo 404 — auch für Admins) | ✗ | RLS: 0 Zeilen |
| `POST /subscriptions/{id}/check` | ✗ (401) | ✗ (403) | ✓ (**nur eigene**; fremdes Abo 404) | ✗ | RLS: 0 Zeilen |

## Tests
- `test_calendar_ics_tz.py` (rein, P9) — DST-Korrektheit des Feeds: die emittierte Serie wird in
  der emittierten Zone expandiert und muss ein Jahr lang 09:00 lesen (**semantisch statt
  textuell**); Onset in Ortszeit im alten Offset; UTC-Events byte-gleich; ganztägig als
  `VALUE=DATE` mit exklusivem `DTEND`; `EXDATE`/`RECURRENCE-ID` in derselben Werteform.
- `test_calendar_subscriptions_http.py` (P9 erweitert) — die sechs `/check`-Tests, darunter
  `test_check_writes_nothing`, das die „reine Probe"-Zusage absichert.
- `test_fetch_ssrf.py` (kernel, P9 erweitert) — ein **Bearer**-Token folgt keinem fremden
  Redirect (negativprobiert) und geht als `Authorization`-Header raus.
- `test_calendar_rls.py` — RLS-Negativ + WITH CHECK (Testcontainers).
- `test_calendar_http.py` — CRUD-Lebenszyklus mit If-Match (428/412/200), Layer-Sichtbarkeit
  (Co-Mitglied sieht `household`, nicht `personal`; fremder personal-Termin 404), owner-only Edit/
  Delete (403), Range-Filter, `ends_at < starts_at` → 422.

## Tests (ergänzt P5-S2)
- `test_calendar_expand.py` — **reine RRULE-Unit-Tests** (FREQ/COUNT/UNTIL/BYDAY/Fenster, ohne Docker).
- `test_calendar_http.py` — zusätzlich: Serie expandiert in Occurrences (gleiche `series_id`),
  ungültige RRULE → 422.

## Tests (ergänzt P5-S5)
- `test_calendar_expand.py` — EXDATE filtert die abgesagte Occurrence (auch über abweichende
  TZ-Repräsentation desselben Instants); `is_occurrence` akzeptiert/verwirft.
- `test_calendar_ics.py` — abgesagte Occurrence wird als `EXDATE`-Zeile gerendert.
- `test_calendar_http.py` — cancel droppt genau eine Instanz (idempotent), restore holt sie zurück,
  Nicht-Serie/Nicht-Occurrence → 422, fremder Nutzer → 403, Feed trägt `EXDATE`.

## Tests (ergänzt P5-S6)
- `test_calendar_ics_parse.py` — **reine Import-Parser-Unit-Tests** (kein Docker): timed/UTC, ganztägig,
  `TZID`→UTC (+ unbekannte Zone → UTC), `RRULE`+`EXDATE`, Faltung/Escaping, VEVENT ohne DTSTART
  übersprungen, **Render→Parse-Round-Trip**.
- `test_calendar_http.py` — Import legt Events an (Serie expandiert), Re-Import dedupt über UID
  (`skipped`), ungültige RRULE → `failed`, `personal`-Layer bleibt vor Co-Mitglied privat.

## Tests (ergänzt P9-S2)
- `test_calendar_creds.py` — **reiner** Encode/Decode-Roundtrip (inkl. Unicode), Tamper/falscher
  Key/Nicht-Credential-Payload → `SecretBoxError` (ohne Docker).
- `test_calendar_subscriptions_rls.py` — RLS-Negativ (A↛B→0, WITH CHECK) **+ `maint_all`-Beweis**
  (`custode_maint` liest cross-household, darf aber nicht schreiben).
- `test_calendar_subscriptions_http.py` — CRUD-Lebenszyklus; **Roh-Body-Assertion** (kein
  Passwort/`creds_enc` in irgendeiner Response); Persistenz `v1:`-Präfix ohne Klartext; beide
  Graceful-Pfade (anonym ohne Key ✓ / Credentials ohne Key → 503); Credentials ersetzen/behalten/
  clearen + 422-Kombinationen; 428/412/ETag; Owner-Scoping (Co-Mitglied → leer/404); Soft-Delete +
  Re-Abo + 409; URL-Form-Validierung; anonym 401.

## Tests (ergänzt P9-S3)
- `test_caldav_client.py` — **reines** Multistatus-Parsing (propstat-404 übersprungen,
  XXE-/Entity-Bomben-Fixtures → `invalid_response`, beweist defusedxml).
- `test_calendar_sync.py` — **reine** Diff-Logik (`_build_wanted`: UID-Gruppierung,
  Override-Ignore, CANCELLED, RRULE-Gate, Längen-Caps; `_differs` inkl. exdates-Instant-Sets).
- `test_fetch_ssrf.py` (erweitert) — `safe_request`: private Ziele geblockt, `allow_private`,
  Credential-Redirect auf fremden Origin geblockt.
- `test_calendar_sync_radicale.py` — Integration gegen gepinntes Radicale (Testcontainer):
  Create/Idempotenz/Update/Delete/Wieder-Auftauchen, `busy`-/`tzid`-Mapping, Auth-Fehler +
  Fehler-Isolation, Keyless-Graceful-Pfad, Null-Adapter-Fail-Safe, Enumeration-Filter,
  S-16-Beweis über `list_busy_intervals`.
- `test_calendar_external_events_http.py` — 409-Read-only-Guards auf allen Write-Pfaden,
  `external`-Flag, personal-Unsichtbarkeit für Mitbewohner, Unsubscribe-Kaskade.

## Tests (ergänzt P9-S4)
- `test_calendar_ics_write.py` — **rein**: `render_single_vevent` (Caller-UID, VALUE=DATE,
  TRANSP, kein METHOD, multibyte-sichere Faltung, Parse-Symmetrie); `patch_vevent`
  (VALARM/ATTENDEE/X-Prop/VTIMEZONE/Override-VEVENT byte-identisch, VALARM-DESCRIPTION-Schutz,
  Insert/Removal/Collapse, RECURRENCE-ID-Skip, Idempotenz, CRLF-Normalisierung);
  `build_patch_changes`.
- `test_calendar_writeback_radicale.py` — Integration: Create→remote sichtbar+Sync idempotent ·
  Edit erhält Fremd-Properties · Zeit/rrule-Clear-Roundtrip · Delete→remote 404 ·
  **echter 412-Konflikt** (Rollback bewiesen) · remote verschwunden (Edit 409/Delete Erfolg) ·
  anonym → 502 `auth_failed` · keyless → 503 · `ext_href NULL` heilt via Sync ·
  ETag-Restamp ohne Update-Zähler.
- `test_calendar_external_events_http.py` — Fake-Port (Recording, `dependency_overrides`):
  PATCH 200 mit GET→PUT-Sequenz (frisches ETag) · Konflikt-Rollback · 422-Gates ·
  DELETE mit gespeichertem ETag · Create-into-Subscription (INM, 404 fremd, 422 kind/tzid) ·
  Occurrence-Ops weiter 409 · lokale Events ohne Port-Call · Kill-Switch → 503.
- `test_fetch_ssrf.py`/`test_caldav_client.py` — Header-Rückgabe; href-Guard (absolute/`//`
  hrefs → `invalid_response` ohne Netz-Call).

## Web (P9, Web-Abo-Verwaltung)
`web/src/calendar/subscriptions-section.tsx` (Sektion auf `/calendar`): Abo-CRUD mit
write-only-Credentials, Status-Zeile je `last_sync_error`-Kategorie, Pause-Toggle
(GET→PATCH, frischer ETag), Edit per Einzel-GET+If-Match. Agenda: „Extern"-Badge,
Occurrence-Aktionen für Spiegel ausgeblendet, externes Löschen mit Confirm;
Create-Formular mit „Ziel-Kalender"-Select (erzwingt `personal/normal/UTC`).
Fehler-Slugs → i18n zentral in `web/src/calendar/errors.ts`; `toProblem` trägt `extra`.

## Offene Punkte (spätere Slices)
- **Phase 9:** Google-OAuth (teilt Infra mit Oura). Der Oura-Block ist gebaut (9-S5…9-S8).
- **Sync-Optimierungen (ADR-0079/0080):** CTag/sync-token (RFC 6578), ETag-Skip,
  RECURRENCE-ID-Overrides spiegeln (+ Occurrence-Writes auf Spiegeln), VTIMEZONE beim Create,
  SEQUENCE/iTIP, DURATION; asynchrone Write-Queue.
- **pro-Instanz-Detailänderung** (Titel/Ort je Occurrence), **Kinder-Kalender**, ggf. strengere
  per-Owner-RLS.
