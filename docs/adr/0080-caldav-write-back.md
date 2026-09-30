# ADR-0080 — CalDAV Write-back: GET-modify-PUT, Property-Erhalt & Remote-first

**Status:** beschlossen · **Phase:** 9 (9-S4) · **Datum:** 2026-07-23

## Kontext

9-S3 (ADR-0079) spiegelt externe Kalender read-only (409 auf jedem Schreibpfad). KONZEPT §6
Stufe 3 verlangt „beidseitig": Termine in Custode anlegen → landen im externen Kalender;
Spiegel editieren/löschen → schreibt durch. Kernproblem: Der Spiegel speichert nur eine
Teilmenge der Remote-Properties — ein naives Re-Rendern beim Edit würde VALARMs, ATTENDEEs
und X-Props des Remote-Events **löschen** (der Feed-Renderer `render_ics` ist zudem verlustig:
UID hartkodiert, kein `VALUE=DATE`/`TRANSP`/`TZID`).

## Entscheidungen

1. **Edit = GET-modify-PUT (`ics_write.patch_vevent`):** Die Ressource wird frisch geholt und
   NUR die geänderten Property-Zeilen werden im Roh-Dokument ersetzt/eingefügt/entfernt —
   lokalisiert über entfaltete logische Zeilen, gespleißt über die physischen Zeilen-Ranges;
   alles Unberührte bleibt byte-identisch (inkl. Original-Faltung). Ein Tiefenzähler schützt
   verschachtelte Komponenten (VALARM-eigene DESCRIPTION); Ziel ist der erste UID-Master ohne
   RECURRENCE-ID. Neu emittierte Zeilen werden RFC-konform bei 75 Oktetten gefaltet
   (multibyte-sicher); Zeilenenden werden auf CRLF normalisiert. `SEQUENCE`/`DTSTAMP` bleiben
   unangetastet (kein iTIP/ATTENDEE-Scheduling — dokumentierte Lücke).
2. **Create = Voll-Render (`ics_write.render_single_vevent`):** eigene Events sind verlustfrei
   renderbar — Caller-UID (`uuid4().hex`), korrekte `VALUE=DATE`-Form, `TRANSP:TRANSPARENT`
   bei `busy=false`, kein `METHOD` (RFC 4791 §4.1). href = Abo-Pfad + `<uid>.ics`; PUT mit
   `If-None-Match: *` (nie überschreiben). UTC-verankert — deshalb 422-Gates beim Create:
   `kind≠normal` (`external_kind_unsupported`) und `tzid≠UTC` (`external_tzid_unsupported`);
   ein stiller Flip beim nächsten Sync-Tick wäre schlimmer als ein ehrliches 422. `layer` wird
   still auf `personal` erzwungen (Spiegel sind per Design personal; der Default `household`
   würde sonst jeden Client zum Mitsenden zwingen).
3. **Edit-Gates:** `layer`/`kind`/`tzid` geändert → 422 `external_field_readonly` (nicht
   round-trip-fähig); gesetzt-und-gleich ist ok (idempotente Clients). Zeit-Edits von
   tzid-Serien rendern `DTSTART;TZID=<tzid>:<lokal>` — die VTIMEZONE steht schon im
   Remote-Dokument und überlebt den Patch (kein VTIMEZONE-Rendering nötig).
4. **ETag-Strategie:** Edit-PUT nutzt das **frische GET-ETag** (minimales Race-Fenster, geht
   auch bei `ext_etag IS NULL`); DELETE nutzt das **gespeicherte** `ext_etag` (kein
   Vorab-GET; NULL → unconditional). Nach einem PUT: Response-ETag, sonst ein
   Best-effort-GET, sonst NULL (der Sync restempelt). Der Pull-Sync stempelt
   `ext_href`/`ext_etag` (Migration 0067) bei **jedem** Lauf — ohne den `updated`-Zähler oder
   SSE zu treiben, wenn nur der ETag rotierte; 9-S3-Alt-Spiegel heilen so binnen eines Ticks
   (bis dahin 409 `external_not_synced`).
5. **Remote-first:** Effektive Werte werden ohne ORM-Mutation berechnet und validiert, dann der
   Remote-Write, erst danach die lokale Anwendung + Emit — jede Exception rollt die Tx zurück,
   die lokale Zeile bleibt bei jedem Fehlschlag unberührt. Bewusste Konsequenz: die
   DB-Transaktion hält während des Remote-I/O eine Connection (durch den CalDAV-Timeout
   begrenzt) — für eine Haushalts-App akzeptiert.
6. **Fehler-Familie:** Remote-412/-409 und beim Edit auch Remote-404 → **409
   `external_conflict`** („Extern geändert — der nächste Sync holt den Stand"; der Sync ist die
   Reconciliation). Remote-404 beim DELETE = Erfolg. Kill-Switch/Null-Adapter → **503
   `caldav_disabled`**; fehlender Server-Key bei Credentials-Abo → **503 `crypto_unconfigured`**
   (ADR-0077); alles andere → **502 `caldav_write_failed`** mit `extra.category`
   (eigene Slugs, nie URL/Credentials/Inhalt). `enabled=false` pausiert nur den Pull —
   Write-through läuft weiter (Pause ≠ Kalender wegsperren).
7. **Occurrence-Aktionen auf Spiegeln bleiben 409** (`external_event_read_only`):
   RECURRENCE-ID-Overrides werden nicht gespiegelt; ein lokales EXDATE würde der nächste Tick
   zurückrollen.
8. **Request-Pfad-Komposition (Mail-Muster):** `main.py` setzt `app.state.caldav =
   build_caldav(settings)`; `kernel/ports/caldav.py::get_caldav(request)` ist die
   FastAPI-Dependency — Module importieren weiterhin nie Adapter. Der Null-Adapter wirft auch
   auf den Write-Ops (`sync_disabled`) — fail-safe statt stiller Divergenz.
9. **href-Guard (Sicherheitsfund):** Server-gelieferte hrefs werden nur als server-absolute
   **Pfade** akzeptiert (`_target`): ein absoluter/protokoll-relativer href würde via `urljoin`
   den Origin tauschen und unsere Credential — Basic wie Bearer — an einen fremden Host tragen
   (Credential-Exfiltration über bösartige REPORT-Antworten).
10. **`safe_request` liefert Response-Header** (`(status, body, headers)`): der PUT-ETag muss
    lesbar sein; Header sind server-kontrolliert und werden nie geloggt. `safe_fetch`-Kontrakt
    unverändert.

## Konsequenzen

- Der Sync ist zwei-Wege: Custode-Termine landen im Nextcloud-Kalender (und umgekehrt);
  Konflikte enden als 409 mit dem Sync als Schiedsrichter. Fremde Erinnerungen/Teilnehmer
  überleben Edits nachweislich (Radicale-Integrationstest mit VALARM/ATTENDEE/X-Prop).
- **Deferred:** VTIMEZONE/TZID-Rendering beim **Create** bleibt offen (Create ist UTC-verankert,
  422-Gate) — der Baustein dafür existiert seit P9 als `calendar/vtimezone.py`, s. ADR-0082 · Occurrence-Writes auf Spiegeln · RECURRENCE-ID-Override-Spiegelung ·
  SEQUENCE-Bump/iTIP · CTag/sync-token (RFC 6578) · asynchrone Write-Queue/Offline-Retry
  (bewusst synchron).
