import { expect, test } from "vitest";

import { dayOfWeekMondayZero, mondayOf, todayIso, todayRange } from "../lib/date";

// Anchor: 2026-01-05 is a Monday (2026-01-01 is a Thursday). Dates are constructed and read in
// local time, so these assertions hold regardless of the runner's timezone.
test("mondayOf returns the Monday of the week", () => {
  expect(mondayOf(new Date(2026, 0, 5))).toBe("2026-01-05"); // Monday itself
  expect(mondayOf(new Date(2026, 0, 7))).toBe("2026-01-05"); // Wednesday -> same Monday
  expect(mondayOf(new Date(2026, 0, 11))).toBe("2026-01-05"); // Sunday -> same Monday
  expect(mondayOf(new Date(2026, 0, 12))).toBe("2026-01-12"); // next Monday
});

test("dayOfWeekMondayZero maps Monday to 0 and Sunday to 6", () => {
  expect(dayOfWeekMondayZero(new Date(2026, 0, 5))).toBe(0); // Monday
  expect(dayOfWeekMondayZero(new Date(2026, 0, 7))).toBe(2); // Wednesday
  expect(dayOfWeekMondayZero(new Date(2026, 0, 11))).toBe(6); // Sunday
});

test("todayIso renders a local YYYY-MM-DD", () => {
  expect(todayIso(new Date(2026, 5, 28, 23, 30))).toBe("2026-06-28");
});

test("todayRange spans exactly the local day containing the instant", () => {
  const noon = new Date(2026, 5, 28, 12, 0, 0);
  const { from, to } = todayRange(noon);
  const fromMs = new Date(from).getTime();
  const toMs = new Date(to).getTime();
  expect(toMs - fromMs).toBe(24 * 60 * 60 * 1000);
  expect(fromMs).toBeLessThanOrEqual(noon.getTime());
  expect(noon.getTime()).toBeLessThan(toMs);
});
