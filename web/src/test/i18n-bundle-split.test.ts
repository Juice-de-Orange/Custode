// Das Gate, das die Katalog-Trennung ehrlich hält.
//
// Die Betreiber-Konsole lädt seit diesem Slice nur noch ihren eigenen Katalog. Das spart ihr 733
// Schlüssel — und schafft eine neue Fehlerart, die vorher unmöglich war: ein Schlüssel, der in
// einer **geteilten** Komponente benutzt wird, aber nur im Mitglieder-Katalog steht, rendert in
// der Konsole als roher Bezeichner. Kein Typfehler, kein Lint-Fund, kein Testfehler anderswo —
// man sieht `state.error` auf dem Bildschirm.
//
// Deshalb prüft dieser Test nicht die Kataloge gegeneinander (das tut `i18n-parity`), sondern
// **jeden Entry gegen das, was er erreichen kann**: von `main.tsx` bzw. `ops/main.tsx` aus wird
// der Import-Graph abgelaufen und jeder darin referenzierte Schlüssel im Katalog *dieses* Entries
// gesucht.
//
// Die Hülle wird statisch berechnet, nicht geraten: dieselbe Menge Dateien, die Vite in das
// jeweilige Bundle legt (relative Importe; npm-Pakete bringen keine eigenen Schlüssel mit).

import { readFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "vitest";

import { messages as de } from "../i18n/locales/de";
import { messages as opsDe } from "../i18n/locales/ops.de";
import { shared } from "../i18n/locales/shared.de";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Resolve a relative import the way Vite would, for the extensions this repo uses. */
function resolveImport(fromFile: string, spec: string): string | null {
  const base = join(dirname(fromFile), spec);
  for (const candidate of [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ]) {
    if (existsSync(candidate) && !candidate.endsWith("/")) {
      try {
        if (readFileSync(candidate).length >= 0) return candidate;
      } catch {
        /* a directory — keep looking */
      }
    }
  }
  return null;
}

/** Every message id a file references, in either of the two forms this codebase uses. */
function keysIn(source: string): string[] {
  const ids = [
    ...source.matchAll(/i18n\._\(\s*"([A-Za-z0-9._]+)"/g),
    ...source.matchAll(/<Trans\s+id="([A-Za-z0-9._]+)"/g),
    ...source.matchAll(/\bid=\{\s*"([A-Za-z0-9._]+)"/g),
  ].map((m) => m[1]);
  // Only ids that look like catalog keys (a dot, lower-case head) — not React element ids.
  return ids.filter((id) => id.includes(".") && /^[a-z]/.test(id));
}

/** Walk the relative-import graph from an entry and collect every referenced message id. */
function reachableKeys(entry: string): { keys: Set<string>; files: number } {
  const seen = new Set<string>();
  const keys = new Set<string>();
  const stack = [entry];
  while (stack.length) {
    const file = stack.pop() as string;
    if (seen.has(file)) continue;
    seen.add(file);
    const source = readFileSync(file, "utf8");
    for (const key of keysIn(source)) keys.add(key);
    for (const m of source.matchAll(/from\s+"(\.[^"]+)"/g)) {
      const target = resolveImport(file, m[1]);
      if (target) stack.push(target);
    }
  }
  return { keys, files: seen.size };
}

test("every key the member app can reach exists in the member catalogue", () => {
  const { keys, files } = reachableKeys(join(SRC, "main.tsx"));
  expect(files).toBeGreaterThan(20); // the walk actually walked
  const missing = [...keys].filter((k) => !(k in de)).sort();
  expect(missing).toEqual([]);
});

test("every key the operator console can reach exists in the OPERATOR catalogue", () => {
  // The one that matters. Before the split this could not fail, because ops shipped everything.
  const { keys, files } = reachableKeys(join(SRC, "ops", "main.tsx"));
  expect(files).toBeGreaterThan(20);
  const missing = [...keys].filter((k) => !(k in opsDe)).sort();
  expect(missing).toEqual([]);
});

test("the operator console does not carry member-only keys", () => {
  // The saving is the point of the slice; without this the split silently rots back.
  const memberOnly = Object.keys(de).filter((k) => !(k in shared));
  const leaked = memberOnly.filter((k) => k in opsDe);
  expect(leaked).toEqual([]);
  expect(Object.keys(opsDe).length).toBeLessThan(Object.keys(de).length / 4);
});

test("shared keys live in exactly one file and reach both catalogues", () => {
  // `shared` is spread into both. If someone later pastes a copy into one of them instead, the
  // two drift apart at the next edit — and only one surface changes.
  for (const key of Object.keys(shared)) {
    expect(de[key]).toBe(shared[key]);
    expect(opsDe[key]).toBe(shared[key]);
  }
});
