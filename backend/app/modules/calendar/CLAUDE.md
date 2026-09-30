# CLAUDE.md — Modul `calendar`

> Ergänzt die Root-`CLAUDE.md`. Bei Konflikt: Sicherheit > KONZEPT/ADR > Root > diese Datei.

## Zweck
Persönlicher + Haushaltskalender (KONZEPT §5.11). P5-S1 = Event-CRUD + Layer-System. RRULE-Serien,
ICS-Im/Export und die Scheduling-Engine kommen in späteren Phase-5-Slices.

## Grenzen (hart)
- Importiert **nur** `kernel/*`, nie ein anderes Modul. Quermodul nur über Events oder `api.py`.
  Jede Fachzeile trägt `household_id`; RLS aktiv (`FORCE`), Negativtest.

## Datenmodell (Migration 0032)
- `calendar_events`: `owner_id`, `title`, `description?`, `location?`, `starts_at`/`ends_at`
  (CHECK `ends_at >= starts_at`), `all_day`, `layer ∈ {household, personal}`, `busy`, `rrule?`
  (RFC-5545, 0033) (+ Mixin).

## Wiederkehrende Events (RRULE, ADR-0041)
- `rrule` macht das Event zur Serie; `starts_at`/`ends_at` = erste Occurrence + Dauer. Expansion in
  `calendar/expand.py` (**rein, ohne DB, DST-sicher via `python-dateutil`**) — **immer gefenstert +
  gedeckelt** (`MAX_OCCURRENCES`); ohne `to` 90-Tage-Horizont. Ungültige Regel → 422.
- **Nie** unbegrenzt expandieren (Endlosserie). `PATCH`/`DELETE` betreffen die **ganze Serie**.

## DST-Korrektheit (P5-S9, ADR-0047)
- Jedes Event trägt `tzid` (IANA, Default `UTC`, Migration 0039). Serien werden **in `tzid`**
  expandiert (`expand.py` ankert `dtstart` in der Zone) → „Montag 09:00 Wien" bleibt über die
  DST-Umstellung um 09:00 Ortszeit. Web sendet die Browser-Zone; ungültige Zone → 422; Expansion
  fällt defensiv auf UTC zurück (nie 5xx). **`is_occurrence` muss dieselbe `tzid` ankern** (sonst
  verfehlt Cancel DST-verschobene Instanzen). **Nie** Serien wieder in UTC ankern.
- **ICS-Feed ist DST-korrekt (P9):** Events mit echter `tzid` gehen als Ortszeit mit `TZID=`
  raus, begleitet von **einer** VTIMEZONE je genutzter Zone (`vtimezone.py`, vor den VEVENTs).
  UTC-Events bleiben unverändert (`…Z`) — Bestandsfeeds verschieben sich nicht.
- **VTIMEZONE trägt explizite `RDATE`-Übergänge, keine geratene `RRULE`.** Eine
  `FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU`-Regel stimmt für EU-Zonen meistens — und verschiebt
  Termine jahrelang still um eine Stunde, wenn nicht. Übergänge werden aus der tz-Datenbank
  **gesampelt**; was `zoneinfo` weiß, bekommt der Abonnent.
- **Der Onset ist Ortszeit im ALTEN Offset** (`TZOFFSETFROM`): Wien-Frühjahr 2026 ist
  `20260329T020000`, nicht `T030000`. Leicht falsch zu machen, teuer wenn falsch.
- `EXDATE`/`RECURRENCE-ID` **müssen dieselbe Werteform + Zone wie `DTSTART`** tragen, sonst
  ignorieren Abonnenten sie stillschweigend.
- **Ganztägig = `VALUE=DATE`**, `DTEND` exklusiv (ein Tag endet am Folgetag).

## Einzel-Occurrence-Ausnahmen (P5-S5, EXDATE, ADR-0043)
- `calendar_events.exdates timestamptz[]` (0036) = abgesagte Einzeltermine (RFC-5545 EXDATE).
  `expand.py` filtert sie instant-genau (DST-sicher) heraus; der ICS-Feed gibt sie als `EXDATE` mit.
- **Schreibpfad ist Mengen-Semantik, nicht If-Match:** `POST /events/{id}/cancel-occurrence`
  (hinzufügen) / `restore-occurrence` (entfernen) — idempotent + kommutativ, darum **kein If-Match**
  (zwei Mitglieder, die verschiedene Instanzen absagen, kollidieren nie). `occurrence_start` muss eine
  **echte** Occurrence sein (`is_occurrence`, sonst 422); Nicht-Serie → 422; owner-only (403).
- **Nie** EXDATE per nacktem PATCH setzen (umgeht `is_occurrence`-Prüfung).

## Einzel-Occurrence verschieben (P5-S10, ADR-0048)
- `calendar_events.overrides` (jsonb, 0040) = `{original_start_iso: {starts_at, ends_at}}`. `expand.py`
  ersetzt die rule-generierte Occurrence durch den Override und liefert `(original_start, start, end)`.
- Schreibpfad wie EXDATE: `POST /events/{id}/move-occurrence` / `reset-occurrence`, owner-only, **kein**
  If-Match (Mengen-Semantik). 422 wenn keine echte Occurrence / abgesagt / Bereich invertiert.
- `EventResponse.original_start` ist der **stabile** Cancel/Move-Schlüssel — Web nutzt ihn (nicht die
  ggf. verschobene `starts_at`). ICS-Feed emittiert pro Override ein VEVENT mit `RECURRENCE-ID`.
- **Nie** Overrides per PATCH setzen; **nie** den verschobenen `starts_at` als Move/Cancel-Schlüssel
  nutzen (immer `original_start`). Pro-Instanz-Titel/Ort = größeres Feature, nicht hier.

## Layer-Sichtbarkeit (ADR-0040)
- RLS isoliert **nur** den Haushalt. `personal` vs `household` läuft **query-seitig**
  (`service._visible`). **Jeder neue Read MUSS `_visible` nutzen** — ein nackter
  `select(CalendarEvent)` würde fremde persönliche Termine zeigen.
- Fremder `personal`-Termin → **404**. Schreiben/Löschen **owner-only** (403 sonst).

## Schreibpfad
- **PATCH + If-Match** (ADR-0034): `version` = ETag (412 stale, 428 fehlend). **Kein Sync-Batch**
  (Kalender ist online-first).

## ICS-Abo-Feed (P5-S3, ADR-0042)
- `calendar_feeds` (0034): pro Mitglied ein Secret-`token`. `GET /v1/calendar/feed/<token>.ics` ist
  **unauthentifiziert** (Token = einzige Credential) und **read-only**; löst den Token cross-household
  über die **maint-Session** (`maint_all`-SELECT-Policy) auf und liest die Events dann **unter dem
  Owner-Scope** (`scoped_session` → RLS + `_visible`). `render_ics` (`ics.py`) ist rein/ohne DB.
- **Nie** den Feed authentifiziert/CSRF-pflichtig machen (Clients senden keine Cookies). **Nie** Events
  im Feed über den maint-Scope lesen (RLS-Umgehung) — immer `scoped_session(household, member)`.
  Wiederkehrende Events als **ein** VEVENT mit `RRULE` (Client expandiert), nicht serverseitig.

## ICS-Import (P5-S6, ADR-0044)
- `POST /v1/calendar/import` nimmt **rohen .ics-Text** (`{content, layer}`) — **kein** serverseitiger
  URL-Fetch, also **keine SSRF-Fläche**. `ics_parse.py` ist rein/ohne DB (Spiegel von `ics.py`):
  UTC/`TZID`/`VALUE=DATE`, `RRULE`, `EXDATE`, Faltung, Escaping; unbekannte Zone → UTC, kaputter
  VEVENT → übersprungen. Dedup über `calendar_events.source_uid` (0037) → Re-Import idempotent.
- **Nie** eine nutzergegebene **URL** serverseitig abrufen (Webcal-Abo = eigener Slice mit SSRF-Guard).
  **Nie** den Parser an DB/Netz koppeln (rein halten).

## Schnittstellen (HTTP)
- `/v1/calendar/events`: `GET ?from=&to=` · `POST` · `GET {id}` (+ETag) · `PATCH {id}` (If-Match) ·
  `DELETE {id}` (Soft) · `POST {id}/cancel-occurrence` / `restore-occurrence` (EXDATE) ·
  `POST {id}/move-occurrence` / `reset-occurrence` (Override, **kein** If-Match) ·
  `POST /import` (ICS-Datei-Upload). Alle **member/admin** (Kinder ✗ in S1), CSRF auf Writes.
- `/v1/calendar/feed`: `POST` (erzeugt/rotiert) · `DELETE` (widerruft) — member/admin, CSRF.
  `GET /v1/calendar/feed/<token>.ics` — **unauth**, read-only.
- `/v1/calendar/subscriptions` (member/admin, CSRF auf Writes, **owner-only** — fremdes Abo 404,
  auch für Admins): `GET` · `POST` · `GET {id}` (+ETag) · `PATCH {id}` (If-Match) · `DELETE {id}`
  (Soft) · `POST {id}/check` — **reine Probe** gegen die gespeicherte URL+Credentials, schreibt
  nichts (auch kein `last_sync_error`), Fehler kommen als **Daten** (`{ok, category, objects}`),
  nicht als Exception.

## Write-back (P9-S4, ADR-0080)
- **Nie fremde VEVENTs re-rendern** — Edits laufen ausschließlich über `ics_write.patch_vevent`
  (GET-modify-PUT): nur geänderte Property-Zeilen werden ersetzt, fremde VALARM/ATTENDEE/
  X-Props bleiben byte-identisch. `render_single_vevent` ist NUR für den Create-Pfad (eigene
  Events, Caller-UID).
- **Immer remote-first:** eff-Werte ohne ORM-Mutation berechnen → validieren → Remote-Write →
  erst dann lokal anwenden + Emit. Jeder Fehlschlag lässt die lokale Zeile unberührt.
- Edit-PUT mit dem **frischen** GET-ETag; DELETE mit dem gespeicherten `ext_etag`; Remote-404
  beim DELETE = Erfolg, beim Edit = 409 `external_conflict`.
- **Nie** ICS-Inhalte, hrefs oder ETags loggen (server-/fremdkontrolliert). hrefs nur als
  server-absolute **Pfade** akzeptieren (`_target`-Guard — Credential-Exfil via urljoin).
- `layer`/`kind`/`tzid` sind auf Spiegeln nicht änderbar (422); Create erzwingt `personal`,
  verlangt `kind=normal` + `tzid=UTC`. Occurrence-Aktionen auf Spiegeln bleiben 409
  (`_reject_external` bleibt in `_series_for_exception` — Overrides werden nicht gespiegelt).
- Der Sync stempelt `ext_href`/`ext_etag` jeden Lauf, zählt aber nur semantische Änderungen.

## Pull-Sync (P9-S3, ADR-0079)
- `sync.py` spiegelt Abos als `calendar_events` mit `subscription_id` (`layer='personal'`,
  Owner = Abonnent, `busy = NOT transparent`, `tzid` erhalten). **Read-only bis 9-S4:** jeder
  Write auf einen Spiegel → 409 `external_event_read_only` (`_reject_external`).
- **Auth als Wertobjekt:** `CaldavAuth(username, password, bearer)` statt paralleler Parameter —
  die Formen schließen sich aus, drei Optionals nebeneinander würden „was, wenn zwei gesetzt sind?"
  an jede Aufrufstelle delegieren. `ANONYMOUS` = öffentliche Kollektion.
  **Beide Formen sind Credentials:** `kernel/fetch` sperrt Redirects für Basic **und** Bearer auf
  dieselbe Origin — ein Bearer-Token ist reines Inhaberrecht ohne eigene Origin-Bindung, ein Leck
  wiegt also schwerer als bei Basic. **Nie** eine Credential am `auth`/`bearer`-Parameter vorbei
  in `headers` schmuggeln: dann greift der Origin-Lock nicht.
- **Port-Kontrakt:** `CaldavPort.list_objects` **wirft** bei Fehlern — `[]` heißt strikt
  „Kollektion leer". Ein Adapter, der bei Fehlern leer antwortet, lässt den Lösch-Diff den
  ganzen Spiegel tombstonen (deshalb wirft auch `NullCaldav`).
- **Nie** die maint-Enumeration ohne `deleted_at IS NULL AND enabled` (BUGLOG 2026-07-08).
  **Nie** Spiegel-Writes unter maint (`maint_all` ist SELECT-only) — immer `scoped_session`
  des Abonnenten. **Nie** URL/Credentials/Titel in Logs (nur Aggregat-Zähler + Kategorie-Slugs).
- `last_sync_at` = letzter **Erfolg**; Fehler setzen nur `last_sync_error` (Kategorie-Slug).
- ICS-Import-Dedup filtert `subscription_id IS NULL` — Spiegel-UIDs sind ein eigener Namensraum.

## Externe CalDAV-Abos (P9-S2, ADR-0077)
- `external_calendar_subscriptions` (0065): pro Mitglied+URL ein Abo. **Owner-only** — jeder Read
  filtert `member_id`; fremdes Abo → **404**, auch für Admins (Credentials sind persönlich).
- **Credentials write-only:** `creds_enc` = **ein** SecretBox-Wert (`v1:`) über `{username, password}`
  (`creds.py` = Format-Kontrakt für den 9-S3-Worker). Verschlüsselung nur im **Service** (eine Stelle
  garantiert: Klartext wird nie persistiert). Responses tragen nur `has_credentials`.
- **Graceful:** `require_secretbox()` (503) **nur** bei Writes mit Credentials — anonyme Abos, Reads,
  Deletes und credential-freie Patches laufen ohne `CUSTODE_CRYPTO_KEY`. Beide Pfade testen.
- **Save-Zeit-Validierung nur Form** (http/https, Host, keine Userinfo, ≤ 2000). **Kein** SSRF-/DNS-
  Check beim Speichern (TOCTOU/Rebinding) — der Guard gehört an die Fetch-Zeit (9-S3, `kernel/fetch`).
- **Nie** Credentials in Response/Log/Event-Payload. **Nie** Klartext persistieren. **Nie** die
  gespeicherte URL serverseitig abrufen (Pull-Sync = 9-S3 mit SSRF-Guard). **Nie** einen
  Subscription-Read ohne `member_id`-Filter.

## Event-Flags (P5-S4)
- `kind ∈ {normal, absence, guest}` (0035). `absence` = Mitglied abwesend, `guest` = Besuch.
  `calendar.api.list_absences(frm, to)` ist die **einseitige** Naht für Scheduling/Fairness
  (Abwesenheit herausrechnen) — kein Modul liest calendar-Tabellen direkt.

## Events
- **publiziert:** `calendar.event.created`/`updated`/`deleted`,
  `calendar.subscription.created`/`updated`/`deleted` → SSE-Entity `"calendar"`.
  **abonniert:** `member.left` (11-S1a, `handlers.py`).
- **Austritt beendet den Kalender-Zugang** (KONZEPT §5.1). Zwei Dinge überlebten ihn sonst, und
  eines war ein Loch: der **ICS-Feed-Token** ist unauthentifiziert (ADR-0042 — Kalender-Apps
  schicken keine Cookies), der Token IST die Zugangskontrolle, und er hatte kein Ablaufdatum und
  keine Bindung an die Mitgliedschaft. Ein entferntes Mitglied las den Haushaltskalender
  **dauerhaft** weiter. Dazu die CalDAV-Abos: sonst holte der 15-Minuten-Cron weiter Termine aus
  dem privaten Kalender einer Person, die nicht mehr dazugehört.

## No-Gos
- **Nie** einen Read ohne `_visible` — sonst leaken persönliche Termine an Mitbewohner.
- **Nie** fremde Termine editieren/löschen lassen (owner-only).
- **Kein Sync-Batch / kein PATCH ohne If-Match.**
