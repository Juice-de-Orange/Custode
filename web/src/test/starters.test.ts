import { expect, test } from "vitest";

import { STARTERS, localizeStarter } from "../lib/starters";

test("there are 15 starter recipes", () => {
  expect(STARTERS).toHaveLength(15);
});

test("starter ids are unique", () => {
  const ids = STARTERS.map((s) => s.id);
  expect(new Set(ids).size).toBe(ids.length);
});

test("localizeStarter picks the German strings", () => {
  const pancakes = STARTERS.find((s) => s.id === "pfannkuchen")!;
  const localized = localizeStarter(pancakes, "de");
  expect(localized.title).toBe("Pfannkuchen");
  expect(localized.ingredients).toContain("250 g Mehl");
  expect(localized.steps_md).toContain("Teig");
});

test("localizeStarter picks the English strings for en locales", () => {
  const pancakes = STARTERS.find((s) => s.id === "pfannkuchen")!;
  const localized = localizeStarter(pancakes, "en");
  expect(localized.title).toBe("Pancakes");
  expect(localized.ingredients).toContain("250 g flour");
});

test("every starter has a title, ingredients and steps in both languages", () => {
  for (const starter of STARTERS) {
    expect(starter.title.de && starter.title.en).toBeTruthy();
    expect(starter.ingredients.length).toBeGreaterThan(0);
    expect(starter.steps.de && starter.steps.en).toBeTruthy();
  }
});
