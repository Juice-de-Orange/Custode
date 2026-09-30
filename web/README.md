# web — Custode PWA

React 19 + TypeScript (strict) + Vite. TanStack Router/Query, Tailwind 4 auf
eigenem Token-Set (ENTWICKLUNGSKONZEPT A.2), Radix-Primitives, Lingui (DE/EN).

```bash
npm install
npm run dev         # http://localhost:5173 (proxyt /v1 → http://localhost:8000)
npm run typecheck   # tsc --noEmit (strict)
npm run lint        # eslint (+ jsx-a11y, react-hooks)
npm run test        # vitest
npm run openapi     # generiert src/api aus ../backend/openapi.json (Vertrag)
npm run build       # tsc --noEmit && vite build
npm run check:pwa   # PWA-Gate: Manifest/SW/Brand-Regel/Ops-Ausschluss (nach build)
npm run size        # Bundle-Size-Gate (CI-blockierend, nach build)
npm run lhci        # Lighthouse-Budgets (CI-blockierend)
```

Regeln: keine hartcodierten Strings (Lingui), **Markenname nur über
`src/lib/brand.ts` `BRAND_NAME`**. Jede Route liefert Loading/Empty/Error
(Trio-Regel, `src/components/states.tsx`). Personenfarben sind Token-Slots.

## PWA (ADR-0078)

Installierbar auf PC + Handy (Manifest + Service Worker, Prompt-Update — nie
Auto-Reload). Der Service Worker ist im Dev-Server standardmäßig **aus**;
testen über den Build:

```bash
npm run build && npm run preview   # http://localhost:4173 → DevTools → Application
# Dev-Server mit SW (nur zum gezielten Testen, danach SW im DevTools deregistrieren):
#   PowerShell: $env:SW_DEV="true"; npm run dev
```

Icons ändern: `public/favicon.svg` anpassen, dann
`npm run generate:pwa-assets` (erzeugt die PNGs in `public/` neu) und die
PNGs **committen**. Der Manifest-Name kommt zur Build-Zeit aus `BRAND_NAME`
(`vite.config.ts`) — nie hartcodieren; `npm run check:pwa` erzwingt das.
