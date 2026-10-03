import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { ThemeToggle } from "../components/theme-toggle";
// The OPS catalog on purpose: the toggle is a shared component, and the console loads only
// `ops.*` + `shared.*`.
import { i18n } from "../i18n/ops";

// Regression (2026-10-03): the console's theme button read "Design: theme.system". The mode
// names lived only in the member catalog, and the bundle-split gate could not see the reference
// because the id is built at runtime (`theme.${pref}`).
test("the theme toggle names every mode in the operator console", () => {
  render(
    <I18nProvider i18n={i18n}>
      <ThemeToggle />
    </I18nProvider>,
  );
  const seen: string[] = [];
  for (let i = 0; i < 3; i += 1) {
    const button = screen.getByRole("button");
    seen.push(button.getAttribute("aria-label") ?? "");
    fireEvent.click(button);
  }
  expect(seen).toEqual(["Design: System", "Design: Hell", "Design: Dunkel"]);
});
