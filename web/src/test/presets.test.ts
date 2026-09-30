import { expect, test } from "vitest";

import { PRESETS, localizePreset } from "../lib/presets";

test("there are three presets with the expected ids", () => {
  expect(PRESETS.map((p) => p.id)).toEqual(["solo", "family", "shared"]);
});

test("every template room reference resolves to a room in the same preset", () => {
  for (const preset of PRESETS) {
    const slugs = new Set(preset.rooms.map((r) => r.slug));
    for (const tpl of preset.templates) {
      if (tpl.room !== undefined) {
        expect(slugs.has(tpl.room)).toBe(true);
      }
    }
  }
});

test("room and template fields stay within the backend bounds", () => {
  for (const preset of PRESETS) {
    for (const room of preset.rooms) {
      expect(room.name.de.length).toBeGreaterThan(0);
      expect(room.name.en.length).toBeGreaterThan(0);
      expect(room.decay_days).toBeGreaterThan(0);
      expect(room.decay_days).toBeLessThanOrEqual(3650);
      expect(room.icon.length).toBeLessThanOrEqual(40);
    }
    for (const tpl of preset.templates) {
      expect(tpl.title.de.length).toBeGreaterThan(0);
      expect(tpl.title.en.length).toBeGreaterThan(0);
      expect(tpl.points).toBeGreaterThanOrEqual(0);
      expect(tpl.points).toBeLessThanOrEqual(100000);
    }
  }
});

test("localizePreset picks the language and preserves slugs and room references", () => {
  const family = PRESETS.find((p) => p.id === "family")!;
  const de = localizePreset(family, "de");
  const en = localizePreset(family, "en");

  expect(de.id).toBe("family");
  expect(de.rooms.map((r) => r.slug)).toEqual(family.rooms.map((r) => r.slug));
  // Kids' room differs across locales -> proves localization happened.
  const deKids = de.rooms.find((r) => r.slug === "kids");
  const enKids = en.rooms.find((r) => r.slug === "kids");
  expect(deKids?.name).toBe("Kinderzimmer");
  expect(enKids?.name).toBe("Kids' room");

  // Defaults are applied and room refs survive localization.
  for (const tpl of de.templates) {
    expect(["fair", "fixed", "open"]).toContain(tpl.rotation);
    if (tpl.room !== undefined) {
      expect(de.rooms.some((r) => r.slug === tpl.room)).toBe(true);
    }
  }
  // The garden chore is outdoor.
  expect(de.templates.some((t) => t.outdoor)).toBe(true);
});

test("shared-flat chores rotate fairly", () => {
  const shared = localizePreset(PRESETS.find((p) => p.id === "shared")!, "de");
  expect(shared.templates.every((t) => t.rotation === "fair")).toBe(true);
});
