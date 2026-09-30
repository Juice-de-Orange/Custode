import { expect, test } from "vitest";

import { DEFAULT_HOUSEHOLD_FLAGS, flagEnabled, getHouseholdFlags } from "../lib/flags";

test("children marketplace is off by default (parity with backend)", () => {
  expect(DEFAULT_HOUSEHOLD_FLAGS.marketplace_children).toBe(false);
});

test("merge keeps only default keys and coerces to boolean", () => {
  const out = getHouseholdFlags({ recipes: 0, unknown: true }, { weather: true });
  expect(Object.keys(out).sort()).toEqual(Object.keys(DEFAULT_HOUSEHOLD_FLAGS).sort());
  expect(out.recipes).toBe(false); // settings_json 0 -> false
  expect(out.weather).toBe(true); // global override
  expect("unknown" in out).toBe(false); // unknown key never leaks in
});

test("settings_json overrides the operator global", () => {
  expect(getHouseholdFlags({ vault: false }, { vault: true }).vault).toBe(false);
});

test("flagEnabled falls back to the static default", () => {
  expect(flagEnabled(undefined, "recipes")).toBe(true);
  expect(flagEnabled({ recipes: false }, "recipes")).toBe(false);
  expect(flagEnabled({}, "nope")).toBe(false);
});
