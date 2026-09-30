// PWA-Gate (ADR-0078). Guards the build-artifact invariants of the installable member app,
// in the same fail-LOUD style as check-bundle-size.mjs:
//   1) dist/ contains a service worker (sw.js) and a web manifest (manifest.webmanifest),
//   2) the manifest name/short_name equal BRAND_NAME from src/lib/brand.ts (brand rule: the
//      marketing name is build-injected, never hardcoded — a rename must only touch brand.ts),
//   3) every icon/screenshot the manifest references actually exists in dist/,
//   4) the member entry (index.html) links the manifest, the ops entry (index-ops.html) does
//      NOT (the operator console must not be installable as the member app), and
//   5) the SW precache contains neither the ops entry nor anything under /v1 (household data
//      must never land in the Cache API — Dexie is the only offline data source).
//
// Run: `npm run build && npm run check:pwa`. Wired into CI (web job) after the size gate.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const DIST = "dist";

function fail(msg) {
  console.error(`[31m✗ ${msg}[0m`);
  process.exitCode = 1;
}

function ok(msg) {
  console.log(`  ${msg} ✓`);
}

if (!existsSync(DIST)) {
  fail(`${DIST} nicht gefunden — zuerst \`npm run build\` ausführen.`);
  process.exit(1);
}

console.log("PWA-Gate — Manifest, Service Worker, Brand-Regel, Ops-Ausschluss:\n");

// 1) Artifacts exist.
const swPath = join(DIST, "sw.js");
const manifestPath = join(DIST, "manifest.webmanifest");
if (!existsSync(swPath)) fail("dist/sw.js fehlt — vite-plugin-pwa nicht gelaufen?");
if (!existsSync(manifestPath)) fail("dist/manifest.webmanifest fehlt.");
if (process.exitCode === 1) process.exit(1);

// 2) Brand rule: manifest name comes from src/lib/brand.ts, nowhere else.
const brandSrc = readFileSync(join("src", "lib", "brand.ts"), "utf8");
const brandMatch = brandSrc.match(/BRAND_NAME\s*=\s*"([^"]+)"/);
if (!brandMatch) {
  fail("BRAND_NAME nicht in src/lib/brand.ts gefunden — Gate kann die Brand-Regel nicht prüfen.");
  process.exit(1);
}
const brand = brandMatch[1];
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (manifest.name !== brand || manifest.short_name !== brand) {
  fail(
    `Manifest name/short_name ("${manifest.name}"/"${manifest.short_name}") ≠ BRAND_NAME ("${brand}") — Manifest muss den Namen aus brand.ts beziehen.`,
  );
} else {
  ok(`Manifest-Name aus BRAND_NAME ("${brand}")`);
}

// 3) Every referenced image exists in dist/ (public/ assets are copied to the dist root).
const images = [
  ...(manifest.icons ?? []),
  ...(manifest.screenshots ?? []),
  ...(manifest.shortcuts ?? []).flatMap((s) => s.icons ?? []),
];
if ((manifest.icons ?? []).length === 0) fail("Manifest hat keine Icons.");
for (const img of images) {
  const rel = img.src.replace(/^\//, "");
  if (!existsSync(join(DIST, rel))) fail(`Manifest referenziert ${img.src}, aber dist/${rel} fehlt.`);
}
if (images.length > 0 && process.exitCode !== 1) ok(`${images.length} Manifest-Bildreferenzen vorhanden`);

// 4) Member entry links the manifest; the ops entry must not.
const memberHtml = readFileSync(join(DIST, "index.html"), "utf8");
const opsHtml = readFileSync(join(DIST, "index-ops.html"), "utf8");
if (!/<link rel="manifest"/.test(memberHtml)) {
  fail("index.html enthält keinen Manifest-Link — PWA-Injection fehlgeschlagen.");
} else {
  ok("index.html verlinkt das Manifest");
}
if (/<link rel="manifest"/.test(opsHtml)) {
  fail("index-ops.html verlinkt das Manifest — die Ops-Konsole darf NICHT installierbar sein (Strip-Plugin defekt?).");
} else {
  ok("index-ops.html ohne Manifest-Link (Ops nicht installierbar)");
}

// 5) SW precache: no ops entry, nothing under /v1. generateSW inlines the precache manifest as
// {url:"...",revision:"..."} entries (minified: keys unquoted) — parse the URL string literals
// instead of grepping the whole file (the navigateFallbackDenylist regex legitimately contains
// the string "/v1/").
const sw = readFileSync(swPath, "utf8");
const precacheUrls = [...sw.matchAll(/"?url"?:\s*"([^"]+)"/g)].map((m) => m[1]);
if (precacheUrls.length === 0) {
  fail("sw.js enthält keine Precache-Einträge — generateSW-Format geändert? Gate misst sonst nichts.");
}
const leakedOps = precacheUrls.filter((u) => u.includes("index-ops") || /(^|\/)ops-[^/]*\.\w+$/.test(u));
if (leakedOps.length > 0) {
  fail(`Ops-Artefakte im Member-Precache: ${leakedOps.join(", ")} (globIgnores prüfen).`);
} else {
  ok(`Precache (${precacheUrls.length} Einträge) ohne Ops-Artefakte`);
}
const leakedApi = precacheUrls.filter((u) => u.replace(/^\//, "").startsWith("v1/"));
if (leakedApi.length > 0) {
  fail(`API-Pfade im Precache: ${leakedApi.join(", ")} — /v1 darf nie gecacht werden.`);
} else {
  ok("Precache ohne /v1-Pfade");
}

if (process.exitCode === 1) {
  console.error("\n[31mPWA-Gate fehlgeschlagen.[0m");
} else {
  console.log("\n[32m✓ PWA-Gate bestanden.[0m");
}
