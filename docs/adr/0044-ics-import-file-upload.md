# ADR-0044 — ICS-Import als Datei-Upload (kein URL-Fetch), Dedup über UID

**Status:** beschlossen · **Datum:** 2026-06-24 · **Phase/Slice:** 5 / P5-S6
**Kontext-Regeln:** Sicherheit > KONZEPT/ADR > Root-CLAUDE > Bequemlichkeit

## Kontext
Der ICS-**Export** (Abo-Feed, ADR-0042) ist live. Das Gegenstück — Termine **aus** einer iCalendar-
Quelle übernehmen — fehlt. Zwei Fragen:
1. **Bezugsweg:** Lädt der Nutzer eine `.ics`-Datei hoch, oder gibt er eine **URL** an, die der Server
   abruft (Webcal-Abo)?
2. **Wiederholter Import:** Wie verhindern wir Duplikate, wenn dieselbe Datei zweimal importiert wird?

## Entscheidung
1. **Datei-Upload, kein serverseitiger URL-Fetch.** Der Client liest die Datei und schickt den
   **rohen Text** (`POST /v1/calendar/import` mit `{content, layer}`, größenbegrenzt). Der Server
   ruft **keine** vom Nutzer kontrollierte URL ab. Damit entfällt die gesamte **SSRF**-Angriffsfläche
   (Root-CLAUDE: „SSRF-Schutz beim Rezept-Import") — kein Fetch interner Adressen, keine
   Redirect-/DNS-Rebinding-Tricks, kein Egress aus dem Cluster. Ein echtes Webcal-**Abo** (periodischer
   Pull mit Allowlist/SSRF-Guard) ist ein bewusst späterer, eigener Slice.
2. **Dedup über die VEVENT-UID.** `calendar_events.source_uid` (Migration 0037, nullable, pro Haushalt
   indiziert) hält die UID des importierten VEVENT. Ein erneuter Import überspringt VEVENTs, deren UID
   im Haushalt bereits existiert → **idempotent**. Selbst angelegte Events bleiben `source_uid = NULL`.
3. **Reiner Parser.** `calendar/ics_parse.py` ist DB-frei und ohne Docker unit-testbar (Spiegel des
   `ics.py`-Renderers). Best-effort-Subset der gängigen Google/Nextcloud/Apple-Exporte: UTC (`Z`) und
   `TZID=`-Zeiten (zoneinfo, unbekannte Zone → UTC statt Abbruch), `VALUE=DATE` (ganztägig), `RRULE`,
   `EXDATE`, Zeilen-Faltung und TEXT-Escaping. Unparsbare VEVENTs (kein DTSTART) werden **übersprungen**,
   nicht als Fehler hochgereicht; ungültige RRULE zählt als `failed`. Rückgabe: `(imported, skipped,
   failed)`.

## Konsequenzen
- **Positiv:** keine SSRF-Fläche; offlinefähiger, simpler Upload; robustes Teil-Parsen (ein kaputter
  Block kippt nicht den ganzen Import); idempotente Re-Importe; reiner Parser → schnelle Tests ohne
  Container; additive Migration.
- **Abwägung:** kein automatisches Abo (Pull) — der Nutzer muss bei Änderungen neu importieren. Das
  Webcal-Abo bleibt ein späterer Slice mit eigener SSRF-/Scheduling-Betrachtung.
- **Grenzen / bewusst nicht in diesem Slice:** VTIMEZONE-Definitionen im File (wir verlassen uns auf
  `TZID`+zoneinfo), VALARM, RECURRENCE-ID-Overrides, Anhänge. Eine UID-Kollision über Haushalte hinweg
  ist unkritisch, da der Dedup-Lookup RLS-/haushaltsgebunden ist.

## Alternativen
- **Server-seitiger URL-Fetch / Webcal-Abo jetzt:** verworfen — bringt SSRF-Risiko und Egress-/
  Scheduling-Fragen, die einen eigenen, abgesicherten Slice verdienen.
- **Dedup über Hash des ganzen VEVENT statt UID:** verworfen — eine geänderte Beschreibung würde als
  neues Event zählen; die UID ist der RFC-konforme stabile Schlüssel.
- **Multipart-File-Upload statt JSON `{content}`:** funktional gleich; JSON hält den generierten
  Client + zod-Vertrag einheitlich mit dem Rest der API.
