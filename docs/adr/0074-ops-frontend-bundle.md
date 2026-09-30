# ADR-0074 — Operator-Konsole als eigenes Frontend-Bundle mit Bearer-Client

**Status:** beschlossen · **Phase:** 8 (P8-S-OPS-FE-a) · **Datum:** 2026-06-30
**Kontext-KONZEPT:** `ARCHITECTURE` §8.6 (Betreiber-Konsole auf eigener Subdomain, eigener
Auth-Stack), §5 (Frontend: ein OpenAPI→Client-Generatorlauf), **ADR-0015** (Betreiber-Grenze),
**ADR-0072** (Operator-Auth: Passwort + TOTP, opake Bearer-Session, kein Cookie/CSRF).

## Kontext
Das Betreiber-Konsole-**Backend** ist vollständig (`/ops/*`: Auth, KPIs, Banner, Flags, Support-
Suche, Feedback-Inbox), hatte aber **kein Frontend**. Die Mitglieder-App ist eine Cookie-/CSRF-
gestützte SPA (`auth/client.ts`). Operatoren authentifizieren sich dagegen über ein **Bearer-Token**
(ADR-0072) und sollen laut §8.6 auf einer **eigenen Subdomain** laufen — Mitglieder-Cookies dürfen
dort nicht im Scope sein und umgekehrt.

Frage: dieselbe SPA mit `/ops`-Routengruppe (schnell, aber Mitglieder-Cookies + Ops-Token teilen
sich eine Origin) **oder** ein getrenntes Bundle auf eigener Subdomain?

## Entscheidung
**Eigenes Bundle auf eigener Subdomain** — §8.6-konform (Sicherheit > Bequemlichkeit).

- **Zweiter Vite-Entry:** `web/index-ops.html` → `web/src/ops/main.tsx`; `vite.config.ts` baut
  beide Bundles (`rollupOptions.input = { main, ops }`). Prod: Caddy serviert das Ops-Bundle für den
  Host `ops.<domain>` und fällt auf `index-ops.html` zurück; `/ops/*` proxyt zur API.
- **Eigener API-Client:** `web/src/ops/client.ts` ist eine **separate** `@hey-api`-Client-Instanz
  (nicht der Mitglieder-Singleton). Request-Interceptor setzt `Authorization: Bearer <token>`; das
  Token lebt **nur im Speicher** (kein localStorage/Cookie → kein XSS-Lift, kein CSRF). Ein Reload
  erzwingt Neu-Login. 401 auf authentifizierten Pfaden verwirft das Token → Redirect auf `/login`.
  **Kein** Silent-Refresh (Operator-Sessions sind kurzlebig).
- **Eigener Router** (`web/src/ops/router.tsx`): `/login` + die per `hasOpsToken()` gewachte
  Konsole. Die globale `Register`-Typaugmentierung bleibt beim Mitglieder-Router (eine zweite würde
  im gemeinsamen tsc-Projekt kollidieren); zur Laufzeit bindet der `RouterProvider` den Ops-Router.
- **Geteilt** werden bewusst nur nebenwirkungsarme Bausteine: Design-System/Tailwind, i18n-Katalog
  (`ops.*`-Schlüssel), `queryClient`, das Trio (`states.tsx`), `Field`, `BRAND_NAME` und der
  **eine** generierte OpenAPI-Client (`/ops/*` ist bereits im Schema). Das RFC-9457-`ProblemError`/
  `toProblem` wandert nach `lib/problem.ts` (von beiden Apps genutzt; `auth/session` re-exportiert
  es für bestehende Call-Sites).

## Konsequenzen
- **Isolation:** ein gestohlenes Ops-Token kann keine Mitglieder-Cookie-Session reiten und
  umgekehrt; getrennte Origins, getrennte Header (eigener CSP-Block, `noindex`).
- **Bundle:** das Ops-Bundle ist schlank (~4,5 kB Entry), teilt sich aber den Vendor-Chunk; Caddy
  serviert für beide Hosts dasselbe `dist/` (geteilte Assets lösen auf beiden Subdomains auf).
- **Dev:** zwei HTML-Entries an einer Origin (`/index-ops.html`) ist für die Entwicklung ok; die
  echte Subdomain-Trennung greift in Prod (Caddy/Tunnel-Route = dokumentierter Infra-Schritt).
- Folge-Slices (S-OPS-FE-b…d) füllen Dashboard/Banner/Flags/Support/Inbox in dieses Gerüst.
