import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import type { NutritionOut } from "../api/types.gen";
import { NutritionPanel } from "../components/nutrition-panel";
import { i18n } from "../i18n";

function renderPanel(overrides: Partial<NutritionOut> = {}) {
  const data: NutritionOut = {
    kcal: 364.4,
    protein_g: 10.2,
    fat_g: 1.0,
    carbs_g: 76.0,
    sugar_g: 0.3,
    fiber_g: 2.7,
    confidence: "complete",
    covered: 1,
    total: 1,
    ...overrides,
  };
  render(
    <I18nProvider i18n={i18n}>
      <NutritionPanel data={data} />
    </I18nProvider>,
  );
}

test("shows rounded kcal and macros", () => {
  renderPanel();
  expect(screen.getByText(/364/)).toBeInTheDocument();
  expect(screen.getByText("Eiweiß")).toBeInTheDocument();
  expect(screen.getByText("10.2 g")).toBeInTheDocument();
});

test("flags estimated nutrition", () => {
  renderPanel({ confidence: "estimated" });
  expect(screen.getByText("geschätzt")).toBeInTheDocument();
});

test("no estimated badge when complete", () => {
  renderPanel({ confidence: "complete" });
  expect(screen.queryByText("geschätzt")).not.toBeInTheDocument();
});
