import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n";

// Stub the router Link so the CTA renders without a router context.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => (
    <a href={to}>{children}</a>
  ),
}));

import { NoHouseholdState } from "../components/no-household";

function renderState() {
  return render(
    <I18nProvider i18n={i18n}>
      <NoHouseholdState />
    </I18nProvider>,
  );
}

describe("NoHouseholdState", () => {
  it("has no axe violations", async () => {
    const { container } = renderState();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("explains the state and points to the account page", () => {
    renderState();
    expect(screen.getByRole("heading", { name: "Kein Haushalt aktiv" })).toBeInTheDocument();
    const cta = screen.getByRole("link", { name: "Zum Konto" });
    expect(cta).toHaveAttribute("href", "/");
  });
});
