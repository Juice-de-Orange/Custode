# ADR-0022: TOTP-2FA (RFC 6238, einstufiger Login, Secret RLS-geschützt)

- **Status:** beschlossen
- **Datum:** 2026-06-17
- **Betrifft:** `kernel/auth`, `modules/accounts` · **Bezug:** KONZEPT §8 (Authentifizierung), §10 (`users.totp?`)

## Kontext

KONZEPT §8 verlangt TOTP-2FA in Phase 1; §10 sieht ein `totp?`-Feld in `users` vor.
Die Cookie-Session-Schicht (ADR-0021) steht. Offen waren: die TOTP-Implementierung
(eigene Lib vs. stdlib), die Form des Logins mit zweitem Faktor und die Speicherung des
TOTP-Secrets (das — anders als der Argon2-Passwort-Hash — reversibel sein muss).

## Entscheidung

**TOTP nach RFC 6238 mit Python-stdlib** (`kernel/auth/totp.py`: HMAC-SHA1, keine eigene
Krypto, **keine neue Abhängigkeit**) — gegen die RFC-6238-Testvektoren verifiziert.
**Einstufiger Login:** `login` nimmt einen optionalen `totp_code`; ist 2FA aktiv und der
Code fehlt/ist falsch, antwortet der Server mit 401 `totp_required` (Passwort war korrekt)
und stellt **keine** Session aus — der Client fragt den Code nach und sendet Login + Code
erneut. **Enrollment:** `POST /v1/auth/totp/setup` erzeugt ein *pending* Secret (+ otpauth-
URI), `enable` bestätigt per Code, `disable` verlangt einen gültigen Code. Das Secret liegt
**RLS-geschützt** im `users`-Row (Self-Policy für Updates, `custode_maint`-SELECT beim
Login-Lookup) — Migration **0008**, additiv.

## Konsequenzen

- **Positiv:** keine neue Lib/Krypto; harte Korrektheit über die RFC-Vektoren; einfacher,
  client-freundlicher Flow; nutzt die vorhandenen Cookie/CSRF/RLS-Bausteine; QR-Erzeugung
  bleibt clientseitig (Backend liefert nur die otpauth-URI).
- **Negativ / Kosten:** das TOTP-Secret ist reversibel und liegt at rest unverschlüsselt
  (nur RLS-geschützt, wie der Passwort-Hash daneben) — ein DB-Leak gäbe die Secrets preis.
  Einstufiger Login sendet bei aktivem 2FA das Passwort ein zweites Mal mit.
- **Auswirkungen:** Migration 0008 (additiv); `login()` um `totp_code` erweitert (Default
  `None`, alte Aufrufer unverändert); `MeResponse.totp_enabled`. Tests: TOTP-Units
  (RFC-Vektoren, lokal) + HTTP-E2E (enroll→login-erfordert-2FA→disable). OpenAPI + Client neu.

## Alternativen (verworfen, mit Begründung)

- **pyotp / externe TOTP-Lib** — RFC 6238 ist mit stdlib-HMAC trivial und testbar; eine Lib
  wäre „neue Technologie ohne belegten Bedarf" (E5). Verworfen.
- **Zweistufiger Login** (Challenge-Token → `/totp/verify`) — bessere UX (Passwort nicht
  erneut), aber extra Endpoint + Challenge-State in Redis. Für den ersten TOTP-Schritt zu
  schwer; als spätere Option offen.
- **Secret verschlüsselt at rest (Fernet o. Ä.)** — sicherer, aber neue Lib + Schlüssel-
  verwaltung inkl. Key auf dem Server. Bewusst als **Härtungs-Folge-Increment** zurückgestellt,
  um einen lauffähigen, verifizierten TOTP-Kern zu liefern. (Recovery-/Backup-Codes sind
  inzwischen umgesetzt: Tabelle `auth_recovery_codes`, SHA-256-gehasht, einmalig, Login-
  Fallback; Migration 0009 — selbe Härtungslinie.)
