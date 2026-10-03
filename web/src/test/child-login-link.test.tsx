import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ChildLoginLink, childLoginUrl } from "../components/child-login-link";
import { i18n } from "../i18n";

const HOUSEHOLD = "0198f3a2-7c1e-7b7e-9d55-2f0a4c1d9e01";

test("the link is the one /child-login reads the household from", () => {
  const url = childLoginUrl("https://custode.example.org", HOUSEHOLD);
  expect(url).toBe(`https://custode.example.org/child-login?household=${HOUSEHOLD}`);
  // Round trip through the same parsing the route uses.
  expect(new URLSearchParams(new URL(url).search).get("household")).toBe(HOUSEHOLD);
});

test("shows the link and copies it", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  render(
    <I18nProvider i18n={i18n}>
      <ChildLoginLink householdId={HOUSEHOLD} />
    </I18nProvider>,
  );
  const expected = `${window.location.origin}/child-login?household=${HOUSEHOLD}`;
  expect(screen.getByText(expected)).toBeInTheDocument();
  expect(screen.queryByRole("status")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Link kopieren" }));
  expect(writeText).toHaveBeenCalledWith(expected);
  expect(await screen.findByRole("status")).toHaveTextContent("Link kopiert.");
});
