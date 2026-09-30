import { expect, test } from "vitest";

import { wmoCondition, wmoIcon } from "../weather/wmo";

test("maps representative WMO codes to condition buckets", () => {
  expect(wmoCondition(0)).toBe("clear");
  expect(wmoCondition(2)).toBe("cloudy");
  expect(wmoCondition(48)).toBe("fog");
  expect(wmoCondition(53)).toBe("drizzle");
  expect(wmoCondition(63)).toBe("rain");
  expect(wmoCondition(81)).toBe("rain");
  expect(wmoCondition(73)).toBe("snow");
  expect(wmoCondition(95)).toBe("thunder");
});

test("unmapped sub-95 codes fall back to cloudy, never blank", () => {
  expect(wmoCondition(49)).toBe("cloudy"); // gap between fog (48) and drizzle (51)
  expect(wmoIcon(0)).toBeTruthy();
});
