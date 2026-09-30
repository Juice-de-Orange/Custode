import { expect, test } from "vitest";

import { listReadyForTrip, TRIP_READY_THRESHOLD } from "../shopping/ready";

test("a list is trip-ready once it reaches the threshold", () => {
  expect(listReadyForTrip(TRIP_READY_THRESHOLD - 1)).toBe(false);
  expect(listReadyForTrip(TRIP_READY_THRESHOLD)).toBe(true);
  expect(listReadyForTrip(TRIP_READY_THRESHOLD + 3)).toBe(true);
});

test("a custom threshold is honoured", () => {
  expect(listReadyForTrip(2, 3)).toBe(false);
  expect(listReadyForTrip(3, 3)).toBe(true);
});
