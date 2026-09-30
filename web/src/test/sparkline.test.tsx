import { render } from "@testing-library/react";
import { expect, test } from "vitest";

import { Sparkline } from "../ops/components/sparkline";

// The sparkline is pure SVG geometry; these lock in the accessible role and the edge cases that
// would otherwise emit NaN coordinates (flat series → divide-by-zero, single point → no polyline).

test("renders an accessible <svg role=img> with the given label", () => {
  const { getByRole } = render(<Sparkline values={[1, 3, 2, 5]} label="Trend X" />);
  const svg = getByRole("img", { name: "Trend X" });
  expect(svg.tagName.toLowerCase()).toBe("svg");
});

test("an empty series renders nothing", () => {
  const { container } = render(<Sparkline values={[]} label="leer" />);
  expect(container.querySelector("svg")).toBeNull();
});

test("a flat series produces finite coordinates (no NaN)", () => {
  const { container } = render(<Sparkline values={[4, 4, 4]} label="flach" />);
  expect(container.querySelector("polyline")?.getAttribute("points")).not.toMatch(/NaN/);
  expect(container.querySelector("path")?.getAttribute("d")).not.toMatch(/NaN/);
  const circle = container.querySelector("circle");
  expect(circle?.getAttribute("cx")).not.toMatch(/NaN/);
  expect(circle?.getAttribute("cy")).not.toMatch(/NaN/);
});

test("a single value renders the end marker but no polyline", () => {
  const { container } = render(<Sparkline values={[7]} label="eins" />);
  expect(container.querySelector("polyline")).toBeNull();
  expect(container.querySelector("circle")?.getAttribute("cx")).not.toMatch(/NaN/);
});
