import { expect, test } from "vitest";

import { messages as de } from "../i18n/locales/de";
import { messages as en } from "../i18n/locales/en";

// Both catalogs are maintained by hand (no extract step) — a missing key renders as its raw id
// in one language only, which no other gate catches. Keep the key sets identical.
test("de and en catalogs carry exactly the same message ids", () => {
  const deKeys = Object.keys(de).sort();
  const enKeys = Object.keys(en).sort();
  expect(deKeys).toEqual(enKeys);
});
