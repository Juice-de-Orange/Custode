# ADR-0025: Auth-Audit ist user-scoped, nicht tenant-scoped

- **Status:** beschlossen
- **Datum:** 2026-06-18
- **Betrifft:** `kernel/auth` · **Bezug:** ARCHITECTURE §12 (Observability/Audit), KONZEPT §8; Roadmap Phase 1 („`login_events` aktiv")

## Kontext

Phase 1 verlangt ein aktives Login-Audit (`login_events`). Die harte Regel (CLAUDE.md)
fordert für **jede neue Fachtabelle** `household_id` + RLS-Negativtest (fremder Haushalt → 0
Zeilen). Login passiert aber **vor** jedem Haushalt: `service.login` läuft im
`maint_session()`-Bootstrap (cross-user), der anmeldende Nutzer kann keinen oder mehrere
Haushalte haben, und ein Fehlversuch mit unbekannter E-Mail hat überhaupt keinen Nutzer. Eine
`household_id`-Spalte hätte hier keine sinnvolle Belegung. Zusätzlich gilt §12: **keine PII in
Logs/Storage** — insbesondere keine IP.

## Entscheidung

**`auth_login_events` ist user-scoped statt tenant-scoped** — RLS keyt auf
`user_id = app.user_id` (wie `auth_sessions`, Migration 0005), **nicht** auf `household_id`.
Der RLS-Negativtest wird entsprechend „User A sieht die Anmeldungen von User B nicht".
Geschrieben wird als `custode_maint` (Login-Bootstrap); ein Nutzer darf seine eigenen
Versuche lesen. Gespeichert wird **nur** `country_code` (2 Zeichen, aus einem Edge-Header wie
`CF-IPCountry`) — **nie IP, E-Mail oder Token**. `user_id` ist **NULL** bei unbekannter
E-Mail (keine Enumeration). Migration **0011**, additiv. Kein OpenAPI-Change (serverintern).

## Konsequenzen

- **Positiv:** konsistent mit dem bestehenden user-scoped Auth-Storage (`auth_sessions`,
  `auth_recovery_codes`, `auth_passkeys`); kein künstliches `household_id` ohne Bedeutung;
  PII-frei (nur Landescode); der Nutzer kann seine Anmeldeversuche einsehen (Sicherheitswert).
- **Negativ / Kosten:** dokumentierte **Ausnahme** vom Wortlaut „jede neue Tabelle hat
  `household_id`" — gilt bewusst nur für pre-tenant Auth-Audit, nie für Fachtabellen.
  Landescode nur vorhanden, wenn der Edge-Header gesetzt ist (sonst NULL; keine eigene
  GeoIP-DB in Phase 1).
- **Auswirkungen:** Migration 0011 (additiv, RLS `user_isolation` + `maint_all`); `login()`/
  `passkey_auth_finish()` um `country_code` erweitert (Default `None`, alte Aufrufer
  unverändert); Audit-Schreibpfad in eigener `maint_session`-Tx, damit die Zeile den 401-
  `raise` überlebt. Tests: RLS-Negativ (user-scoped), PII-Schema-Assertion, Erfolg/Fehlschlag/
  unbekannte E-Mail.

## Alternativen (verworfen, mit Begründung)

- **`household_id` pro Regelwortlaut** — pre-tenant nicht belegbar (kein/mehrere Haushalte,
  Fehlversuch ohne Nutzer). Eine Pflicht-`household_id` wäre hier semantisch leer. Verworfen.
- **IP speichern (für Geo/Forensik)** — verstößt gegen §12 (keine PII); Landescode genügt für
  „ungewöhnlicher Ort". Verworfen.
- **Eigene GeoIP-DB (MaxMind o. Ä.)** — neue Abhängigkeit + Datenpflege; der Edge-Proxy
  liefert ein Länder-Header (`geo_country_header`, Default `CF-IPCountry`) bereits. Als Null-Adapter zurückgestellt.
