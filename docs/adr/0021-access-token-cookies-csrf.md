# ADR-0021: Opaque Redis-Access-Token, Cookie-Sessions & CSRF

- **Status:** beschlossen
- **Datum:** 2026-06-17
- **Betrifft:** `kernel/auth`, `kernel/http`, `modules/accounts` · **Bezug:** KONZEPT §8 (Transport & Sessions), ARCHITECTURE §7 (`/v1`), §9 (RLS), §12 (Referenzcodes)

## Kontext

Die Auth-Service-Schicht (Registrierung, Login, opaque rotierende Refresh-Sessions
mit Reuse-/Theft-Detection in `auth_sessions`) war fertig, aber ohne HTTP-Oberfläche.
KONZEPT §8 fordert verbindlich: kurzlebige **Access-Tokens** + Refresh-Rotation, sichere
**Cookie-Flags** (httpOnly, Secure, SameSite=Lax), **CSRF-Schutz** und Geräte-Liste mit
Remote-Logout. Offen war ausschließlich die Form des Access-Tokens und der HTTP-Vertrag.
Redis ist bereits Pflicht-Infrastruktur (`/readyz`, ARCHITECTURE §8.4/§13), opaque
SHA-256-gehashte Tokens sind bereits das etablierte Muster (`kernel/auth/tokens.py`).

## Entscheidung

**Das Access-Token ist ein opaques, serverseitig in Redis gehaltenes Token** (TTL =
`access_token_ttl_s`, 15 min). Gespeichert wird nur sein SHA-256-Hash als Key, der Wert
sind die Principal-Claims (`user_id`, aktives `household_id|None`, `role|None`,
`family_id`). Pro Request: Access-Cookie → Redis-Lookup → `Principal` → `set_principal()`
→ RLS-Scope. Sessions sind **cookiebasiert** (kein `Authorization: Bearer`): drei Cookies
— Access (Path `/`), Refresh (Path `/v1/auth`), CSRF (nicht-httpOnly). **CSRF** ist ein
Double-Submit-Cookie + `X-CSRF-Token`-Header, erzwungen auf unsicheren Methoden außer dem
Login/Logout-Bootstrap. Dev schaltet `Secure` + den `__Host-`-Präfix ab (http://localhost);
Prod nutzt `__Host-` für Access/CSRF. Der aktive Haushalt einer Login-Familie liegt in
Redis (`active_household:{family_id}`, TTL = Refresh-TTL) und wird beim Refresh mitgeführt.

**JWT wurde verworfen.** Es bringt keinen belegten Vorteil (E5: „Das Bestehende scheitert
nachweislich an X" ist für JWT unbelegt), erfordert eine neue Krypto-Lib (ADR-pflichtig)
samt Schlüsselverwaltung und erlaubt **keine prompte Sperrung** innerhalb der TTL — was
Remote-Logout und Theft-Revoke (KONZEPT §8) schwächt.

## Konsequenzen

- **Positiv:** sofortige Sperrung (Logout/Theft revoziert die ganze Familie über den
  Index `access_family:{family_id}`); keine neue Abhängigkeit; konsistent mit dem
  Opaque-Refresh-Muster; Token-Klartext nie persistiert; Cookie-Politik an genau einer
  Stelle (`kernel/http/cookies.py`).
- **Negativ / Kosten:** ein Redis-Lookup pro authentifiziertem Request (Redis ohnehin
  Pflicht); aktiver Haushalt überlebt ein abgelaufenes Access-Token nur via Redis-Key,
  nicht im Token selbst.
- **Auswirkungen:** keine DB-Migration für Access (Redis-only). Für die haushalts-
  übergreifenden **Lesepfade** (Invite per Code, eigene Haushalte listen, Mitgliedschaft
  vor Switch prüfen) wurde der maint-Lesezugriff additiv erweitert (Migration **0007**,
  spiegelt 0006 für `users`, SELECT-only); Schreibvorgänge bleiben `custode_app`, gescopt
  auf den serverseitig abgeleiteten Ziel-Haushalt. Tests: HTTP-E2E mit Testcontainers
  PG+Redis (CI) + lokale Unit-Tests (Cookies/CSRF/Access-Store). OpenAPI + Web-Client neu
  generiert.
- **Offen (eigene Increments):** TOTP, Passkeys (WebAuthn), Kinder-PIN, Geräte-Listen-UI;
  vollständige Security-Header/CSP-Härtung (`SecurityHeadersMiddleware`).

## Alternativen (verworfen, mit Begründung)

- **Signiertes JWT als Access-Token** — neue Lib ohne belegten Bedarf (E5), schwächere
  Sperrung innerhalb der TTL, Schlüsselverwaltung. Widerspricht „keine neue Technologie
  ohne ADR" und dem Remote-Logout-Ziel.
- **`Authorization: Bearer` statt Cookies** — KONZEPT §8 schreibt Cookie-Flags + CSRF
  vor; Bearer im JS-Speicher ist XSS-exponiert. Verworfen.
- **CSRF auf Logout erzwingen** — Logout ist idempotent und niedrigschwellig; SameSite=Lax
  blockt den Cross-Site-POST ohnehin. Logout bleibt CSRF-frei, damit ein Logout ohne
  Sitzung sauber 204 liefert.

**Nachtrag P9 (2026-07-30):** `SameSite=Lax` + `path=/` ist seit Phase 9 nicht mehr nur eine
CSRF-Abwägung, sondern eine **Zusicherung**, auf der Code beruht: `peek_access_user_id`
(`kernel/auth/dependencies.py`) liest das Access-Cookie auf einer *unauthentifizierten* Route und
bindet damit den OAuth-Callback an den Browser, der den Flow gestartet hat. Genau weil `Lax` das
Cookie bei der Top-Level-GET-Navigation vom Provider mitschickt, funktioniert das. Eine
Verschärfung auf `Strict` bricht diese Bindung **still** — der Callback sähe dann nie eine Session
und würde jeden Grant ablehnen. Herleitung: ADR-0081 §4, Fund: `docs/BUGLOG.md` 2026-07-30.
