import { expect, test } from "vitest";

import { findDurationMinutes, parseSteps, scaleLine } from "../lib/cook";

test("parseSteps splits lines and strips list markers", () => {
  expect(parseSteps("1. Teig kneten\n2. Backen")).toEqual(["Teig kneten", "Backen"]);
  expect(parseSteps("Schritt eins\n\n- Schritt zwei")).toEqual(["Schritt eins", "Schritt zwei"]);
  expect(parseSteps("   ")).toEqual([]);
});

test("scaleLine scales the leading quantity", () => {
  expect(scaleLine("250 g Mehl", 2)).toBe("500 g Mehl");
  expect(scaleLine("2 Zwiebeln", 0.5)).toBe("1 Zwiebeln");
  expect(scaleLine("1/2 TL Salz", 2)).toBe("1 TL Salz");
  expect(scaleLine("1,5 kg Kartoffeln", 2)).toBe("3 kg Kartoffeln");
});

test("scaleLine leaves lines without a number unchanged", () => {
  expect(scaleLine("etwas Pfeffer", 2)).toBe("etwas Pfeffer");
});

test("scaleLine produces fractional German formatting", () => {
  expect(scaleLine("100 g Butter", 1.5)).toBe("150 g Butter");
  expect(scaleLine("1 Ei", 0.5)).toBe("0,5 Ei");
});

test("findDurationMinutes detects a duration", () => {
  expect(findDurationMinutes("10 Minuten köcheln")).toBe(10);
  expect(findDurationMinutes("ca. 5 Min anbraten")).toBe(5);
  expect(findDurationMinutes("Teig kneten")).toBeNull();
  expect(findDurationMinutes("200 ml Wasser")).toBeNull();
});
