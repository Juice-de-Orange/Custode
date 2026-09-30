import { expect, test } from "vitest";

import { effectivePoints, isOverdue } from "../tasks/decay";

const NOW = new Date("2026-06-23T12:00:00Z");
const daysAgo = (n: number) => new Date(NOW.getTime() - n * 86400000).toISOString();

test("full value when not overdue or no due date", () => {
  expect(effectivePoints(10, null, NOW)).toBe(10);
  expect(effectivePoints(10, new Date(NOW.getTime() + 3600000).toISOString(), NOW)).toBe(10);
});

test("decays 10% per whole day overdue, floored at 50% (mirrors backend)", () => {
  expect(effectivePoints(10, daysAgo(1), NOW)).toBe(9);
  expect(effectivePoints(10, daysAgo(3), NOW)).toBe(7);
  expect(effectivePoints(10, daysAgo(6), NOW)).toBe(5);
  expect(effectivePoints(10, daysAgo(100), NOW)).toBe(5);
});

test("isOverdue reflects a past due date", () => {
  expect(isOverdue(null, NOW)).toBe(false);
  expect(isOverdue(daysAgo(1), NOW)).toBe(true);
  expect(isOverdue(new Date(NOW.getTime() + 3600000).toISOString(), NOW)).toBe(false);
});
