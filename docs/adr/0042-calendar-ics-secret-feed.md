# ADR-0042: Kalender-ICS-Feed — unauthentifizierter Secret-Token, read-only, maint-Lookup

- **Status:** beschlossen
- **Datum:** 2026-06-24
- **Betrifft:** `modules/calendar` · **Bezug:** KONZEPT §5.11, ADR-0040 (Layer), Auth-Token-Lookup (maint)
- **Phase/Slice:** P5-S3

## Kontext

Nutzer wollen ihren Custode-Kalender in Google/Nextcloud/Apple **abonnieren** (ICS-Feed). Solche
Kalender-Clients holen die `.ics`-URL periodisch und **ohne Cookies/Session** — der bestehende
Cookie+CSRF-Auth-Pfad funktioniert dort nicht. Es braucht also einen **unauthentifizierten** Endpoint,
der trotzdem nur die Termine **eines** Mitglieds liefert und Mandanten-Isolation wahrt.

## Entscheidung

1. **Secret-Token als einzige Credential.** Pro Mitglied ein `calendar_feeds`-Eintrag mit einem
   hochentropen `token` (`secrets.token_urlsafe(32)`). Der Feed ist `GET /v1/calendar/feed/<token>.ics`
   — **kein** Auth-Dependency, **kein** CSRF (Lesen). Der Token ist das Geheimnis (wie ein
   Passwort-Reset-/Secret-iCal-Link).
2. **Cross-Household-Lookup über die maint-Session.** Da der Aufrufer anonym ist, wird der Token
   haushaltsübergreifend aufgelöst — `calendar_feeds` bekommt zusätzlich zur `household_isolation` eine
   **`maint_all`-SELECT-Policy** für `custode_maint` (genau das Muster des Auth-Token-Lookups, Mig.
   0006/0007/0021). Danach werden die Events **unter dem Haushalts-Scope des Besitzers** gelesen
   (`scoped_session(household_id, member_id)`) → RLS + `_visible` (ADR-0040) gelten unverändert.
3. **Read-only & widerrufbar.** Nur Lesen; der Token wird per `POST /v1/calendar/feed` erzeugt **oder
   rotiert** (alter Link tot) und per `DELETE` widerrufen. `include_in_schema=False` für den
   `.ics`-GET (kein Client-Typ nötig).
4. **Inhalt = iCalendar mit RRULE.** Wiederkehrende Events werden als **ein** VEVENT mit `RRULE`
   ausgegeben; der Client expandiert — keine serverseitige Expansion, kein Horizont-Problem.

**Nachtrag P9 (2026-07-30) zu Punkt 4:** Der Feed-Inhalt ist seit Phase 9 **zonenbehaftet** —
Events mit echter `tzid` gehen als `DTSTART;TZID=` mit einer `VTIMEZONE` je genutzter Zone raus,
Ganztags-Events als `VALUE=DATE` mit exklusivem `DTEND`; UTC-Events sind byte-gleich zu vorher.
Serien bleiben **ein** VEVENT mit `RRULE` (der Client expandiert), aber jetzt in der richtigen Zone.
Begründung und Grenzen: [ADR-0082](0082-ics-feed-vtimezone.md).

## Konsequenzen

- **Positiv:** Standard-konformes Kalender-Abo ohne Cookies; Mandanten-/Layer-Isolation bleibt intakt
  (Events via Owner-Scope + `_visible`). Token rotier-/widerrufbar. ICS-Rendering ist rein + ohne DB
  testbar.
- **Negativ / Kosten:** Ein **bekanntes** Geheimnis-in-der-URL-Modell: wer den Link hat, sieht die
  Termine (UI warnt „nicht teilen"). Token landet ggf. in Server-Logs Dritter (Kalender-Anbieter) —
  akzeptiert, Industriestandard; Mitigation = Rotation/Widerruf. Eine zweite RLS-Policy (`maint_all`)
  auf der Feed-Tabelle (klar begrenzt: nur SELECT, nur Token-Auflösung).

## Alternativen (verworfen)

- **Authentifizierter Feed (Cookie/Token-Header)** — Kalender-Clients senden keine Cookies/Custom-Header
  beim Abo. Unbrauchbar.
- **HTTP-Basic-Auth in der URL** (`https://user:pass@…`) — exponiert echte Credentials, von vielen
  Clients schlecht unterstützt. Verworfen.
- **Signiertes, ablaufendes JWT in der URL** — bricht das „dauerhaft abonnieren"-Modell (Feed muss
  langlebig sein); Rotation/Widerruf deckt den Sicherheitsbedarf einfacher ab. Verworfen.
