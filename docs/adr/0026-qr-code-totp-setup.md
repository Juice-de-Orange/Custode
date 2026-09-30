# ADR-0026: QR-Code für TOTP-Setup (clientseitig, `qrcode.react`)

- **Status:** beschlossen
- **Datum:** 2026-06-19
- **Betrifft:** `web` (Security-Center) · **Bezug:** KONZEPT §8 (Authentifizierung), ADR-0022 (TOTP-2FA), Roadmap Phase 1

## Kontext

ADR-0022 hält fest, dass die TOTP-QR-Erzeugung **clientseitig** bleibt — das Backend liefert
bei `POST /v1/auth/totp/setup` nur die `otpauth://`-URI (inkl. `issuer=BRAND_NAME`). Im
Security-Center (S8) muss der Nutzer diese URI in seine Authenticator-App übernehmen. Die URI
als reinen Text anzuzeigen und abtippen zu lassen ist fehleranfällig (langer Base32-Secret) und
schlechte UX; nahezu alle Authenticator-Apps erwarten einen QR-Scan. Einen QR-Code clientseitig
zu rendern erfordert QR-Matrix-Erzeugung samt Reed-Solomon-Fehlerkorrektur — das von Hand zu
implementieren ist unverhältnismäßig und fehlerträchtig. Es braucht also eine kleine Web-Lib;
neue Abhängigkeiten verlangen einen ADR.

## Entscheidung

**Die `otpauth://`-URI wird clientseitig als QR gerendert, mit `qrcode.react` (Komponente
`QRCodeSVG`).** Synchrone SVG-Ausgabe (keine async `toDataURL`-Effekte), gut für A11y
(skaliert scharf, `aria-label` setzbar) und in Vitest/jsdom trivial prüfbar (gerendertes
`<svg>`). Das **Secret bleibt zusätzlich als manueller Fallback** sichtbar, falls eine App
keinen Scan erlaubt. Kein Backend-/Migrations-/OpenAPI-Change — die URI existiert bereits.

*Verfeinerung gegenüber der Plan-Vornotiz „`qrcode`":* das React-Paket `qrcode.react` ist die
idiomatische Variante; das Low-Level-`qrcode` bräuchte einen async `toDataURL`-Effekt plus
`<img>`. Die Entscheidung „QR-Lib gleich einbauen" bleibt unverändert.

## Konsequenzen

- **Positiv:** robuste App-Einrichtung per Scan; keine Server-Abhängigkeit (kein PNG-Endpoint,
  keine zusätzliche Route/Last); SVG ist scharf & barrierearm; deterministisch testbar; manueller
  Secret-Fallback erhält den Basis-Pfad (Graceful Enhancement).
- **Negativ / Kosten:** eine neue Web-Abhängigkeit (`qrcode.react`, klein — Bundle-Budget bleibt
  eingehalten, im Lighthouse/Bundle-Gate zu bestätigen).
- **Auswirkungen:** `web/package.json` (+`qrcode.react`); genutzt in
  `web/src/components/totp-setup.tsx`; Vitest prüft das gerenderte `<svg>` + den Secret-Fallback.
  Kein Backend/Contract berührt → `git diff web/src/api/` bleibt leer.

## Alternativen (verworfen, mit Begründung)

- **`otpauth://`-URI nur als Text** — kein QR, Nutzer tippt den Base32-Secret ab. Fehleranfällig,
  schlechte UX, von Authenticator-Apps kaum unterstützt. Verworfen (Anlass dieses ADR).
- **Server-gerendertes QR-PNG** — koppelt die UI an einen neuen Backend-Endpoint und Bildausgabe
  ohne Mehrwert; widerspricht ADR-0022 („QR bleibt clientseitig"). Verworfen.
- **Low-Level `qrcode` (`toDataURL`)** — funktioniert, erzwingt aber async Effekt + `<img>` statt
  einer synchronen React-Komponente; schlechter test- und a11y-seitig. Verworfen zugunsten `qrcode.react`.
