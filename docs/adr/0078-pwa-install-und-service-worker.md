# ADR-0078 — PWA: Installierbarkeit + Service Worker (vite-plugin-pwa, Prompt-Update)

**Status:** beschlossen · **Phase:** 8 (Web-Polish, Querschnitt) · **Datum:** 2026-07-19
**Kontext-KONZEPT:** §7.2/§7.3 (Web zuerst; „begrenzter Offline-Modus"), `ARCHITECTURE` §5
(Frontend-Web-PWA — mit diesem ADR neu gefasst), §10 (Sync-Batch), `UX_KONZEPT` §7
(„Mobile-Browser ist gleichwertig"), ADR-0032 (Sync-Batch = einziger Offline-Schreibpfad),
ADR-0074 (Ops-Konsole als eigenes Bundle/Subdomain), ADR-0075 (Design-Tokens).

## Kontext
Custode soll auf PC und Handy **installierbar** sein (Standalone-Fenster, Home-Screen-Icon),
mit dem Handy als primärem Nutzungskontext. Bisher existierte keinerlei PWA-Substanz: kein
Manifest, kein Service Worker, nur ein 32×32-SVG-Favicon. Die alte ARCHITECTURE-§5-Formulierung
(„Workbox — App-Shell-Precache, **Stale-While-Revalidate für GET-Whitelist, Background Sync für
die Offline-Outbox**") stammt aus der Konzeptphase und hält der Realität 2026 in zwei Punkten
nicht stand — nach Prinzip E9 wird erst das Konzept korrigiert (dieses ADR + §5-Update), dann
gebaut.

## Entscheidung

### Werkzeug: `vite-plugin-pwa` (Workbox generateSW), `registerType: "prompt"`
- **generateSW** deklarativ statt handgeschriebenem SW: Precache aller gehashten Build-Artefakte
  (JS/CSS/HTML/SVG/PNG/WOFF2 → die komplette App-Shell inkl. Fonts und libsodium-Lazy-Chunk
  öffnet offline; ausgenommen Nicht-Latin-Font-Subsets ~90 KiB — DE+EN braucht sie nie, online
  bleiben sie via unicode-range abrufbar), `navigateFallback: /index.html` für SPA-Deep-Links,
  `inlineWorkboxRuntime: true` (genau **ein** `sw.js` → eine `no-cache`-Regel in Caddy).
- **Prompt-Update statt `autoUpdate`:** Custode ist eine Dateneingabe-App — ein Auto-Reload
  mitten im Formular/Kochmodus ist inakzeptabel. Neuer SW wartet; ein leiser Toast („Neue
  Version verfügbar" / „Neu laden" / „Später") übergibt die Kontrolle. Update-Checks laufen
  stündlich und bei Rückkehr in die App (`visibilitychange`) — eine installierte App navigiert
  sonst wochenlang nicht und sähe nie ein Update.
- **Stale-Chunk-Doppelschutz:** (a) der wartende SW serviert alte Hash-Chunks weiter aus dem
  Precache, bis der Nutzer das Update annimmt; (b) `vite:preloadError` → einmaliger Reload
  (Session-Flag gegen Loops) fängt den Rest (reine Browser-Tabs, die einen Deploy überholen).

### Abweichung 1: **keine API-Antworten im SW-Cache** (statt „SWR-GET-Whitelist")
`/v1` wird vom SW **nicht angefasst** (kein `runtimeCaching`, Navigations-Denylist für
`/v1|/ops|/metrics|/healthz|/readyz`). Gründe: (a) Datenschutz — gecachte Haushaltsdaten
überleben sonst den Logout auf geteilten Geräten; (b) eine zweite Offline-Datenquelle neben
Dexie erzeugt Konsistenz-Doppelstaat; (c) der Logout-Purge bleibt trivial (nur Dexie + Query-
Cache, der SW-Cache enthält ausschließlich öffentliche Shell-Dateien). **Dexie hinter dem
Sync-Batch (ADR-0032) ist und bleibt die einzige Offline-Datenquelle.** Ergänzend: Logout
flusht erst die Outbox (Push mit 3-s-Timeout, solange die Session lebt), dann werden alle
Dexie-Tabellen und der React-Query-Cache geleert; ein Write-Block verhindert, dass ein noch
laufender Pull den Cache danach wieder befüllt (aufgehoben beim nächsten erfolgreichen
`/v1/auth/me`). **Offline-Logout verwirft ungepushte Änderungen bewusst** — Logout gewinnt.

### Abweichung 2: **Vordergrund-Sync statt Background-Sync-API**
iOS/Safari implementiert Background Sync nicht — eine Architektur, die darauf baut, wäre auf
dem primären Zielgerät tot. Der bestehende Outbox-Retry (bei `online`-Event, App-Fokus,
nächster Nutzung) ist der Basis-Pfad und bleibt es (Graceful-Enhancement-Prinzip).

### Manifest & Brand-Regel
- `id: "/"`, `scope: "/"`, `start_url: "/today"` (der tägliche Hub, erster Mobile-Tab),
  `display: standalone`; `theme_color`/`background_color` = `--color-kalk` (#fafaf7) — die
  Dark-Variante regeln die bestehenden media-basierten `theme-color`-Metas zur Laufzeit.
- **`name`/`short_name` werden zur Build-Zeit aus `src/lib/brand.ts` injiziert** (Import in
  `vite.config.ts`) — der Marketingname steht nirgends statisch; ein Namenswechsel bleibt eine
  Ein-Zeilen-Änderung. Das CI-Gate `check:pwa` erzwingt die Gleichheit maschinell.
- Icons aus neuer Generator-Pipeline (`pwa-assets.config.ts`, Quelle `public/favicon.svg`,
  committete PNGs): 192/512 „any", 512 **maskable** (Motiv in der 40-%-Safe-Zone auf
  Laurus-Grün), 180 **opakes** Apple-Touch-Icon (iOS rendert Transparenz schwarz).
- `shortcuts` (Heute/Einkauf/Aufgaben) mit Labels aus dem **deutschen Lingui-Katalog zur
  Build-Zeit** (bleiben synchron zur In-App-Navigation): das Manifest ist eine statische Datei
  (`lang: "de"`); Manifest-Lokalisierung ist bewusst außerhalb des Scopes.
- **Ops-Konsole ist NICHT installierbar:** vite-plugin-pwa injiziert den Manifest-Link in alle
  HTML-Entries — ein Post-Plugin strippt ihn aus `index-ops.html`; Ops-Chunks sind vom
  Member-Precache ausgeschlossen. `check:pwa` erzwingt beides.

### Standalone-Korrektheit (Pflichtteil, nicht Politur)
`viewport-fit=cover` + `env(safe-area-inset-*)` an Bottom-Bar, „Mehr"-Sheet, Palette-FAB und
Kochmodus — ohne das kollidiert die Bottom-Bar in iOS-Standalone mit dem Home-Indicator
(„installierbar, aber kaputt"). `overscroll-behavior-y: none` **nur** im Standalone-Fenster
(kein versehentlicher Pull-to-Refresh mitten in einer Eingabe; Browser-Tabs unverändert).

### Infrastruktur (Caddy)
`/assets/*` (content-gehasht) → `Cache-Control: public, max-age=31536000, immutable`; **alles
andere** (`sw.js`, `manifest.webmanifest`, `index.html`, SPA-Fallback) → `no-cache`. Ein lange
gecachtes `sw.js` würde installierte Apps auf einer alten Version einfrieren. CSP-Report-Only
beider Blöcke um `worker-src 'self'` ergänzt.

## Bewusste Abgrenzungen
- **iOS-Splash-Screens (`apple-touch-startup-image`) verschoben:** ~20 media-gequerte PNGs für
  einen ~0,5-s-Moment; `background_color` + Pre-Paint-Theme-Script mildern den Start bereits.
  Nachrüstbar über die bestehende Generator-Pipeline.
- **Kein Push in diesem Schritt** (braucht Backend-Subscriptions + iOS Declarative Web Push —
  eigener Slice, wenn Benachrichtigungen anstehen).
- **Manifest-`screenshots`** („Richer Install UI" auf Android/Desktop) folgen im
  Feinschliff-PR, sobald die Safe-Area-UI final aussieht (`**/screenshots/**` ist im Precache
  bereits ausgenommen).

## Konsequenzen
- Neues CI-Gate `npm run check:pwa` (nach dem Build): Manifest + `sw.js` existieren,
  Manifest-Name === `BRAND_NAME`, alle Bildreferenzen vorhanden, Member verlinkt das Manifest,
  Ops nicht, Precache ohne Ops-Artefakte und ohne `/v1`-Pfade.
- SW-Registrierung + Toast kosten ~3 kB gzip im Eager-Payload (Budget 220 kB, Stand ~197).
- Dev-SW nur opt-in (`SW_DEV=true`), sonst gilt: bauen + `npm run preview` testen.
- Tests: Update-Toast (Render, Callbacks, axe), Logout-Purge (alle Dexie-Tabellen leer).
