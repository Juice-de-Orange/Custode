import { expect, test } from "vitest";

import { i18n } from "../i18n";

// Regression guard — BUGLOG "i18n prod interpolation": Lingui only interpolates COMPILED messages in a
// production build; a raw-string catalog renders literal {placeholders} (and unresolved ICU plurals)
// once minified. dev/jsdom compiles on the fly and masks it, so a render test cannot catch a regression
// to raw catalogs. Instead assert the ACTIVE catalog is stored in Lingui's compiled token form.
test("the active catalog is compiled, not raw strings", () => {
  // "theme.toggle" = "Design: {mode}" → compiled ["Design: ", ["mode"]] (an array, not a string).
  const compiled = i18n.messages["theme.toggle"];
  expect(compiled).toBeDefined();
  expect(typeof compiled).not.toBe("string");
});

test("interpolation and ICU plurals resolve without literal placeholders", () => {
  expect(i18n._("theme.toggle", { mode: "System" })).toBe("Design: System");
  expect(i18n._("today.points.value", { count: 1 })).toBe("1 Punkt");
  expect(i18n._("today.points.value", { count: 3 })).toBe("3 Punkte");
});
