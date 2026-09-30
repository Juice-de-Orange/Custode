# ADR-0023: Passkeys (WebAuthn) — py-webauthn, request-derived RP

- **Status:** beschlossen
- **Datum:** 2026-06-17
- **Betrifft:** `kernel/auth`, `modules/accounts` · **Bezug:** KONZEPT §8 (Authentifizierung), §10 (`users.passkeys[]`)

## Kontext

KONZEPT §8 verlangt **Passkeys (WebAuthn) ab V1**. Die WebAuthn-Verifikation (CBOR-
Attestation, COSE-Public-Keys, ES256-Signaturen, `authenticatorData`/Sign-Count, Origin/
RP-Id-Bindung) ist sicherheitskritische Krypto, die man nicht selbst implementieren darf.
Offen waren: die Bibliothek, die Herkunft von rp_id/Origin (Config vs. Request), die
Challenge-Ablage und der Login-Flow.

## Entscheidung

**WebAuthn über `py-webauthn`** (`verify_registration_response` / `verify_authentication_
response`) — **keine eigene Krypto** (E5: Eigenbau scheitert nachweislich an der Korrektheits-/
Sicherheitslatte). Tests treiben die volle Zeremonie mit **`soft-webauthn`** (Dev-Dependency,
Software-Authenticator). **rp_id und expected origin werden aus dem Request abgeleitet**
(`Origin`/`Host`) — funktioniert auf localhost und der Live-Domain **ohne Konfiguration**;
eine Origin-Abweichung lässt die Verifikation **fail-closed** scheitern. Die Challenge liegt
kurzlebig in **Redis** (Registrierung per `user_id`, passwortlose Auth per Flow-Cookie).
**Passwortloser Login** (discoverable credentials): `login/begin`+`login/complete` →
opaque Refresh-Session (wie Passwort-Login). Credentials in `auth_passkeys` (`credential_id`
b64url, COSE `public_key` b64url, `sign_count`), RLS `user_isolation` + `maint_all`
(Migration 0010; maint für den Cross-User-Lookup am Login).

## Konsequenzen

- **Positiv:** korrekte, gewartete WebAuthn-Krypto; **ops-frei** (keine RP-Config auf dem Server);
  nutzt die vorhandenen Session-/RLS-/Redis-Bausteine; QR/Client bleiben im Browser.
- **Negativ / Kosten:** neue Dependencies — `py-webauthn` (prod, transitiv `cryptography`/
  `pyasn1`/`pyOpenSSL`) und `soft-webauthn` (dev). Request-derived RP vertraut dem eigenen
  Origin (Same-Origin-SPA); eine explizite RP-Allowlist ist eine spätere Härtung.
- **Auswirkungen:** Migration 0010 (additiv); `uv.lock` aktualisiert; Live-Smoke nur bis
  `begin` möglich (die volle Zeremonie braucht Browser/Authenticator → in CI via
  soft-webauthn). 6 Routen unter `/v1/auth/passkeys`.

## Alternativen (verworfen, mit Begründung)

- **Eigenbau-WebAuthn** — sicherheitskritische Krypto; E5 „Bestehendes scheitert an X" gilt
  hier umgekehrt: Eigenbau scheitert an der Sicherheitslatte. Verworfen.
- **rp_id/Origin fest per Settings/Server-Env** — strenger, aber Ops-Schritt auf dem Live-
  Server. Request-derived ist ops-frei und fail-closed; Allowlist bleibt als Option offen.
- **Nicht-discoverable (Passkey nur als Zweitfaktor mit E-Mail-Hint)** — schwächere UX;
  passwortloser, discoverable Login ist das Ziel von KONZEPT §8.
