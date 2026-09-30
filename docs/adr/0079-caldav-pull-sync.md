# ADR-0079 — CalDAV Pull-Sync: Spiegel-Modell, Protokoll & Fail-Safes

**Status:** beschlossen · **Phase:** 9 (9-S3) · **Datum:** 2026-07-23

## Kontext

9-S2 (ADR-0077, Migration 0065) hat externe CalDAV-Abos als Datenmodell + CRUD geliefert. 9-S3
holt die Termine: ein 15-min-Cron ruft jede aktive Kollektion ab und spiegelt ihre Events, damit
sie im Kalender erscheinen und das Scheduling-„belegt"-Signal füttern (KONZEPT §6 Stufe 3,
Synergie S-16). Zu entscheiden: Speichermodell, Protokoll/Bibliotheken, Sync-Semantik,
Fehler-/Sicherheitsverhalten, Kill-Switch.

## Entscheidungen

1. **Spiegel-Modell:** Externe Termine werden `calendar_events`-Zeilen mit neuer nullable Spalte
   `subscription_id` (FK auf das Abo, Migration 0066), `layer='personal'`, `owner_id` = Abo-Inhaber,
   `source_uid` = VEVENT-UID. Damit greifen `_visible`, RRULE-Expansion, DST-Maschinerie und
   `list_busy_intervals` **unverändert**: Der Spiegel blockt genau die Slots des Abonnenten und
   bleibt für Mitbewohner unsichtbar (konsistent zu 9-S2: Abos sind owner-only). Der im KONZEPT
   skizzierte „eigene Layer" ist eine **Darstellungs**-Eigenschaft: `EventResponse.external: bool`
   (additiv) — die spätere Web-Slice rendert Badge/Layer-Filter und unterdrückt Edit-Controls.
2. **Read-only bis Write-back (9-S4):** Jeder Schreibpfad (PATCH/DELETE/Occurrence-Aktionen) auf
   einem Spiegel-Event antwortet **409** `external_event_read_only` — der Konflikt ist ein
   Ressourcen-Zustand (Quelle ist der externe Server), keine Berechtigungsfrage (der Owner ist ja
   der Abonnent).
3. **Löschsemantik:** `DELETE /subscriptions/{id}` tombstoned in derselben Transaktion alle
   Spiegel-Events. `enabled=false` pausiert ohne zu löschen. Reaper-Allow-List um
   `external_calendar_subscriptions` **und** `calendar_events` erweitert — bewusste Nebenwirkung:
   auch lokal gelöschte Termine purgen jetzt nach dem 30-Tage-Fenster (ARCH §9). FK
   `ON DELETE CASCADE` als Backstop beim Hard-Delete des Abos.
4. **Sync = Full-Fetch + Diff:** Pro Lauf **ein** `REPORT calendar-query` ohne time-range
   (Haushaltskalender sind klein; nur der Voll-Abruf macht den Lösch-Diff korrekt — mit Fenster
   wären „außerhalb" und „gelöscht" ununterscheidbar). Diff per `(subscription_id, uid)`:
   create / update (Feldvergleich) / soft-delete. Partieller Unique-Index
   `(subscription_id, source_uid) WHERE deleted_at IS NULL` als Race-Backstop.
   *Notierte Optimierungen (später):* CTag/sync-token (RFC 6578), ETag-Skip pro Objekt,
   RECURRENCE-ID-Overrides spiegeln, VTIMEZONE-Custom-Zonen, DURATION.
5. **Parser-Erweiterungen statt neuer Lib:** `ics_parse` (ADR-0044-Pfad) additiv um
   `TRANSP:TRANSPARENT` (→ `busy=false` — Geburtstage blocken kein Scheduling),
   `STATUS:CANCELLED` (→ wie remote gelöscht), `RECURRENCE-ID` (Override-Erkennung: Master
   gewinnt, Overrides werden diese Scheibe ignoriert — naive UID-Dedup hätte Serien
   verdoppelt/verworfen) und `tzid`-Erhalt (DST-korrekte Serien, ADR-0047) erweitert.
6. **Keine `caldav`-Bibliothek:** synchron (blockierende requests-HTTP-Schicht ohne unseren
   SSRF-Guard) und für einen einzigen REPORT überdimensioniert. Die KONZEPT-§6-Vorgabe
   „bewährte Bibliotheken" wird dort erfüllt, wo das Risiko liegt: **defusedxml** (neue direkte
   Dependency; XXE/Entity-Bomben aus nutzerkonfigurierten Servern) fürs Multistatus-XML,
   `python-dateutil` für RRULE (bestehend).
7. **Fetch-Schicht:** `kernel/fetch.safe_request` — Geschwister von `safe_fetch` mit derselben
   SSRF-Garantie (Scheme-Whitelist, jede aufgelöste Adresse public, manuell re-validierte
   Redirects, Size-/Time-Caps), plus: **mit Credentials werden Redirects auf denselben Origin
   beschränkt** (Basic-Auth wandert nie zu fremden Hosts — *seit P9 gilt das für jede
   Credential-Form, s. Nachtrag unten*). Worker-taugliche `FetchError`-Klassen
   statt HTTP-`ProblemException`. `CUSTODE_CALDAV_ALLOW_PRIVATE_URLS` (Default aus) lockert
   **nur** den Public-Address-Check — für Dev/Tests (Radicale im Compose) und Self-Hosted-Ziele.
8. **Port-Kontrakt: Fehler werfen.** `CaldavPort.list_objects` liefert Roh-ICS pro Ressource
   (Parsen modulseitig — adapters dürfen modules nicht importieren) und **wirft** `CaldavError`
   bei jedem Fehler: `[]` heißt strikt „Kollektion leer", sonst würde ein Netzwerk-Blip per
   Lösch-Diff den ganzen Spiegel tombstonen. Aus demselben Grund **wirft auch `NullCaldav`**
   (`sync_disabled`) statt leer zu antworten — der neutrale No-Op eines Diff-Syncs ist
   „nichts anfassen".
9. **Fehler-Isolation dreistufig:** kaputter VEVENT → Event übersprungen; kaputtes Abo →
   `last_sync_error` = Kategorie-Slug (`unreachable`, `auth_failed`, `not_calendar`,
   `invalid_response`, `too_large`, `blocked_url`, `crypto_unconfigured`, `creds_undecryptable`,
   `sync_disabled`; nie URL/Inhalt), Schleife läuft weiter; kaputter Lauf → Log + nächster Tick.
   `last_sync_at` = letzter **Erfolg** (Stale-Signal); beides gestempelt unter `scoped_session`
   (die `maint_all`-Policy ist bewusst SELECT-only). Ohne `CUSTODE_CRYPTO_KEY` pausieren nur
   Credentials-Abos; anonyme syncen weiter (ADR-0077).
10. **Cron & Kill-Switch:** `5,20,35,50 * * * *` (weicht den :00/:30-Reapern aus), Enumeration
    unter maint **mit** `deleted_at IS NULL AND enabled`-Filter (BUGLOG-Checkliste 2026-07-08).
    Kill-Switch = Settings-Flag `CUSTODE_CALDAV_SYNC_ENABLED` (aus → Job kehrt vor der
    Enumeration um; der werfende Null-Adapter ist der Fail-Safe dahinter). Die in ARCHITECTURE
    §8.4 genannte `external`-Queue bleibt aspirational — es existiert weiterhin ein einzelner
    Broker; ein Multi-Queue-Umbau wäre ein eigener Infrastruktur-Slice.

## Konsequenzen

- Externe Termine erscheinen binnen ≤ 15 min, blocken Scheduling-Slots des Abonnenten und
  verschwinden mit dem Abo. Betreiber-Handgriffe: `CUSTODE_CRYPTO_KEY` (für Credentials-Abos),
  optional `CUSTODE_CALDAV_SYNC_ENABLED=0` als globaler Stopp.
- Tests: Radicale-Testcontainer (gepinnt `tomsquest/docker-radicale:3.7.6.0`, htpasswd/plain)
  beweist Create/Update/Delete/Auth/Isolation; reine Suiten decken Multistatus-Parsing (inkl.
  XXE-Abwehr), Diff-Logik und `safe_request`-Guards ab. Dev-Compose enthält denselben Radicale
  für manuelles Testen (`infra/radicale/`, Dev-Login custode:custode).
- Lokal gelöschte Kalender-Termine sind nach 30 Tagen endgültig weg (vorher: Tombstones für
  immer) — dokumentiert im CHANGELOG.

**Nachtrag P9 (2026-07-30):** Die Redirect-Origin-Sperre gilt für **jede** Credential-Form, nicht
nur Basic — `kernel/fetch.safe_request` nimmt seit dem Bearer-Fundament ein eigenes `bearer=` und
sperrt daran genauso. Ein Bearer-Token im `headers`-Dict wäre dem Schutz sonst entgangen, und das
wiegt schwerer als bei Basic: ein Bearer-Token ist reines Inhaberrecht ohne Origin-Bindung.
Die Invariante samt Auflage („Credentials nie an `auth=`/`bearer=` vorbei in `headers`") steht als
Nachtrag in ADR-0030. Zu Punkt 8: die Auth-Parameter des Ports sind seit P9 ein Wertobjekt
`CaldavAuth` (Basic | Bearer | `ANONYMOUS`) statt zweier Optionals, und die Slug-Familie ist um
`conflict`/`not_found` gewachsen (9-S4, ADR-0080 §6).
