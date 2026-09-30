// Bundle-Size-Gate (Phase 8, Roadmap L316-319 / ADR-0075 Perf-Constraint).
//
// Guards two invariants of the built app, name-/hash-agnostic so it survives chunk renames:
//   1) the eager initial payload of each entry (member index.html + operator index-ops.html) stays
//      within a gzip budget, and
//   2) the ~520 kB libsodium-wasm wrapper stays a SEPARATE LAZY chunk — present in the output but
//      referenced by NEITHER entry HTML (it must load only when the vault is opened).
//
// "Eager" is read straight from the built HTML: the entry <script type="module">, every
// <link rel="modulepreload"> (JS) and every <link rel="stylesheet"> (render-blocking CSS) is what
// the browser fetches on first paint. Lazy chunks (dynamic import()) are not preloaded, so they
// never appear here. gzip -9 is a stable proxy for the gzip/brotli transfer size Caddy serves.
//
// Scope caveat: only the JS + CSS the HTML references are budgeted. Fonts (@fontsource, loaded via
// CSS @font-face with font-display:swap — async, subset-gated) and any wasm fetched by a JS loader
// are out of scope by design; the libsodium wasm is guarded explicitly below.
//
// The gate is written to fail LOUD, never fail open: if it cannot even find an entry's own chunk
// (e.g. a vite `base`/`assetsDir` change breaks the ref format) it errors instead of passing empty.
//
// Run: `npm run build && npm run size`. Wired into CI (web job) after the build.

import { gzipSync } from "node:zlib";
import { readFileSync, readdirSync, existsSync } from "node:fs";
import { join } from "node:path";

const DIST = "dist";
const ASSETS = join(DIST, "assets");

// Budgets in gzipped kB (JS + eager CSS). Set with ~10-15 % headroom over the current baseline so a
// real new dependency trips the gate while routine changes do not. Baseline @ 2026-07 after route
// code-splitting (Slice 5f): member ~197 (was ~233 — the routes are now lazy chunks), ops ~138 (incl.
// the shared ~8.5 kB CSS). `entryChunk` is the entry's own chunk prefix — the gate asserts it is
// actually found, so a broken ref format fails loud instead of measuring nothing.
//
// 2026-08-01, ops von 160 auf 145: die Konsole lud bis dahin den kompletten i18n-Katalog der
// Mitglieder-App — 820 Schlüssel, von denen sie 73 benutzt. Nach der Trennung steht sie bei
// ~135,5 statt ~159,6 kB. Das Budget wandert mit, sonst wächst der Gewinn still wieder zu: ein
// Budget mit 24 kB Luft misst nichts mehr. 145 lässt weiterhin ~7 % für echten neuen Code.
const ENTRIES = [
  { html: "index.html", entryChunk: "main", label: "Member-App (index.html)", budgetKb: 220 },
  { html: "index-ops.html", entryChunk: "ops", label: "Operator-Konsole (index-ops.html)", budgetKb: 145 },
];
// A lazy chunk that must never become eager. Matched by filename prefix (vite names it by package).
const LAZY_REQUIRED = [{ prefix: "libsodium", label: "libsodium-wasm" }];

function gzKb(file) {
  return gzipSync(readFileSync(join(ASSETS, file)), { level: 9 }).length / 1024;
}

// Filenames of the JS + CSS assets a built HTML entry loads eagerly (entry script, modulepreloads,
// stylesheet links). Accepts both absolute (/assets/…) and relative (./assets/… or assets/…) refs
// so a vite base change does not silently zero the measurement.
function eagerAssetsOf(html) {
  const src = readFileSync(join(DIST, html), "utf8");
  const files = new Set();
  for (const m of src.matchAll(/(?:src|href)="\.?\/?assets\/([^"]+\.(?:js|css))"/g)) files.add(m[1]);
  return [...files];
}

function fail(msg) {
  console.error(`[31m✗ ${msg}[0m`);
  process.exitCode = 1;
}

if (!existsSync(ASSETS)) {
  fail(`${ASSETS} nicht gefunden — zuerst \`npm run build\` ausführen.`);
  process.exit(1);
}

const allAssets = readdirSync(ASSETS);
const allJs = allAssets.filter((f) => f.endsWith(".js"));

// Coverage: every built HTML entry must be budgeted here, else a new vite input would ship an
// entirely unmeasured payload AND let libsodium leak into it undetected.
const builtHtml = readdirSync(DIST).filter((f) => f.endsWith(".html"));
for (const html of builtHtml) {
  if (!ENTRIES.some((e) => e.html === html)) {
    fail(`Entry "${html}" ist gebaut, aber im Bundle-Size-Gate nicht erfasst (ENTRIES ergänzen).`);
  }
}

const eagerEverywhere = new Set();

console.log("Bundle-Size-Gate — eager Initial-Payload je Entry (gzip, JS + CSS):\n");

for (const entry of ENTRIES) {
  const files = eagerAssetsOf(entry.html);
  files.forEach((f) => eagerEverywhere.add(f));

  // Fail loud if the gate could not even find the entry's own chunk — otherwise an empty match set
  // would pass every downstream check while measuring nothing.
  if (!files.some((f) => f.startsWith(`${entry.entryChunk}-`) || f === `${entry.entryChunk}.js`)) {
    fail(`${entry.label}: Entry-Chunk "${entry.entryChunk}-*" nicht in ${entry.html} gefunden — Ref-Format geändert? Gate misst sonst nichts.`);
    continue;
  }

  const perFile = files.map((f) => ({ f, kb: gzKb(f) })).sort((a, b) => b.kb - a.kb);
  const total = perFile.reduce((s, x) => s + x.kb, 0);
  const ok = total <= entry.budgetKb;
  console.log(`  ${entry.label} — ${total.toFixed(1)} kB / ${entry.budgetKb} kB Budget ${ok ? "✓" : "✗"}`);
  for (const { f, kb } of perFile) console.log(`      ${kb.toFixed(1).padStart(7)} kB  ${f}`);
  if (!ok) fail(`${entry.label}: ${total.toFixed(1)} kB gzip überschreitet Budget ${entry.budgetKb} kB.`);
}

console.log("\nLazy-Chunk-Garantie:");
for (const { prefix, label } of LAZY_REQUIRED) {
  const chunks = allJs.filter((f) => f.startsWith(prefix));
  if (chunks.length === 0) {
    fail(`${label}: kein separater Chunk (Prefix "${prefix}") gefunden — vermutlich ins Haupt-Bundle gewandert.`);
    continue;
  }
  const leaked = chunks.filter((f) => eagerEverywhere.has(f));
  if (leaked.length > 0) {
    fail(`${label}: eager geladen (${leaked.join(", ")}) — muss Lazy-Chunk bleiben.`);
  } else {
    const kb = chunks.reduce((s, f) => s + gzKb(f), 0);
    console.log(`  ${label}: lazy ✓ (${chunks.length} Chunk(s), ${kb.toFixed(1)} kB gzip, nicht im Initial-Payload)`);
  }
}

if (process.exitCode === 1) {
  console.error("\n[31mBundle-Size-Gate fehlgeschlagen.[0m");
} else {
  console.log("\n[32m✓ Bundle-Size-Gate bestanden.[0m");
}
