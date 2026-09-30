import { resolve } from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { VitePWA } from "vite-plugin-pwa";

import { messages as deMessages } from "./src/i18n/locales/de";
import { BRAND_NAME } from "./src/lib/brand";

// vite-plugin-pwa injects the manifest <link> into EVERY rollup HTML entry, but the operator
// console (index-ops.html, own subdomain, ADR-0074) must not be installable as the member app.
// Strip the link from the ops entry after the PWA plugin ran; scripts/check-pwa.mjs asserts the
// result on every build.
function stripManifestFromOps(): Plugin {
  return {
    name: "custode:strip-manifest-from-ops",
    enforce: "post",
    transformIndexHtml: {
      order: "post",
      handler(html, ctx) {
        if (!ctx.filename.endsWith("index-ops.html")) return html;
        return html.replace(/\s*<link rel="manifest"[^>]*>/, "");
      },
    },
  };
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installable PWA (ADR-0078): app-shell precache with prompt-style updates. The service
    // worker deliberately never handles /v1 — Dexie is the only offline data source (privacy on
    // shared devices; logout purge stays trivial). Brand rule: the marketing name is
    // build-injected from src/lib/brand.ts, never hardcoded here.
    VitePWA({
      registerType: "prompt", // data-entry app: never reload under the user's feet
      injectRegister: false, // registration lives in PwaUpdateToast (useRegisterSW)
      manifest: {
        id: "/",
        name: BRAND_NAME,
        short_name: BRAND_NAME,
        // Same brand-free product description as the index.html meta.
        description:
          "Die ruhige Haushaltsplattform: Rezepte, Einkauf, Aufgaben, Kalender, Notizen und mehr — durchdacht und an einem Ort.",
        lang: "de",
        start_url: "/today",
        scope: "/",
        display: "standalone",
        // --color-kalk; the dark variant is handled at runtime by the media-query
        // <meta name="theme-color"> tags in index.html (a manifest value is static).
        theme_color: "#fafaf7",
        background_color: "#fafaf7",
        icons: [
          { src: "/pwa-192x192.png", sizes: "192x192", type: "image/png" },
          { src: "/pwa-512x512.png", sizes: "512x512", type: "image/png" },
          {
            src: "/maskable-icon-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
        // Richer Install UI (Android Chrome 94+/Desktop 108+): with screenshots + description
        // the install prompt becomes an app-store-style sheet. Captured from the live app
        // (light theme, German); narrow = 390x844@2x. Excluded from the precache (globIgnores).
        screenshots: [
          {
            src: "/screenshots/mobile-today.png",
            sizes: "780x1688",
            type: "image/png",
            form_factor: "narrow",
            label: "Heute-Übersicht",
          },
          {
            src: "/screenshots/mobile-shopping.png",
            sizes: "780x1688",
            type: "image/png",
            form_factor: "narrow",
            label: "Einkaufsliste",
          },
          {
            src: "/screenshots/wide-today.png",
            sizes: "1280x800",
            type: "image/png",
            form_factor: "wide",
            label: "Heute-Übersicht",
          },
        ],
        // Long-press/right-click jump list on the installed icon. Labels come from the German
        // Lingui catalog at build time so they track the in-app nav wording; the manifest is
        // one static file (lang "de") — per-locale manifests are out of scope (ADR-0078).
        shortcuts: [
          {
            name: deMessages["nav.today"],
            url: "/today",
            icons: [{ src: "/pwa-192x192.png", sizes: "192x192" }],
          },
          {
            name: deMessages["nav.shopping"],
            url: "/shopping",
            icons: [{ src: "/pwa-192x192.png", sizes: "192x192" }],
          },
          {
            name: deMessages["nav.tasks"],
            url: "/tasks",
            icons: [{ src: "/pwa-192x192.png", sizes: "192x192" }],
          },
        ],
      },
      workbox: {
        // Precache the complete app shell (hashed chunks, fonts, icons) so the installed app
        // opens offline. Content-hashed filenames make cache-first safe.
        globPatterns: ["**/*.{js,css,html,svg,png,woff2}"],
        // The ops entry + its own chunks stay out of the member precache (rollup names the ops
        // entry chunk after its input key — the same assumption check-bundle-size.mjs makes).
        // Screenshots (PR 2) are install-UI-only and never needed at runtime. Non-Latin font
        // subsets (~90 KiB) stay out of the install payload of this DE+EN app — they remain
        // loadable online on demand via their unicode-range @font-face rules.
        globIgnores: [
          "**/index-ops.html",
          "**/assets/ops-*.*",
          "**/screenshots/**",
          "**/assets/*cyrillic*.woff2",
          "**/assets/*greek*.woff2",
          "**/assets/*vietnamese*.woff2",
        ],
        // SPA deep links resolve offline; API/infra paths and the ops entry must never be
        // answered with the member shell.
        navigateFallback: "/index.html",
        navigateFallbackDenylist: [
          /^\/v1\//,
          /^\/ops/,
          /^\/metrics/,
          /^\/healthz/,
          /^\/readyz/,
          /index-ops\.html$/,
        ],
        inlineWorkboxRuntime: true, // a single sw.js file → one no-cache rule in Caddy
        cleanupOutdatedCaches: true,
        // Workbox's default 2 MiB per-file cap stays: today's largest chunk (libsodium,
        // ~520 kB) fits comfortably, and a future chunk that outgrows the cap SHOULD fail the
        // precache-count assertions in check-pwa.mjs rather than silently bloat every install.
        // NO runtimeCaching on purpose: /v1 responses (household data) must never land in the
        // Cache API. Offline data lives in Dexie behind the sync batch (ADR-0032/0078).
      },
      // The dev service worker is opt-in only (stale-SW confusion): SW_DEV=true npm run dev.
      devOptions: { enabled: process.env.SW_DEV === "true" },
    }),
    stripManifestFromOps(),
  ],
  build: {
    // Two entries from one project: the member SPA (index.html) and the operator console
    // (index-ops.html). They ship as separate bundles; in prod the ops bundle is served on
    // its own subdomain (ARCHITECTURE §8.6, infra/caddy/Caddyfile).
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
        ops: resolve(__dirname, "index-ops.html"),
      },
    },
  },
  server: {
    port: 5173,
    // dev proxy so the SPA / ops console can call the API without CORS config
    proxy: {
      "/v1": "http://localhost:8000",
      "/ops": "http://localhost:8000",
    },
  },
});
