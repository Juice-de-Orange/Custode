import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { DashboardTile } from "../components/dashboard-tile";
import { i18n } from "../i18n";

// Stub the router Link so the tile can render its „alle ansehen" affordance without a router.
vi.mock("@tanstack/react-router", () => ({
  Link: ({ to, children }: { to: string; children: React.ReactNode }) => <a href={to}>{children}</a>,
}));

function renderTile(props: Partial<Parameters<typeof DashboardTile>[0]> = {}) {
  render(
    <I18nProvider i18n={i18n}>
      <DashboardTile
        title="Titel"
        isLoading={false}
        isError={false}
        isEmpty={false}
        {...props}
      >
        <p>Inhalt</p>
      </DashboardTile>
    </I18nProvider>,
  );
}

test("renders the heading as a labelled section", () => {
  renderTile({ to: "/tasks" });
  expect(screen.getByRole("region", { name: "Titel" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "alle ansehen" })).toHaveAttribute("href", "/tasks");
});

test("shows the content branch", () => {
  renderTile();
  expect(screen.getByText("Inhalt")).toBeInTheDocument();
});

test("shows the loading branch", () => {
  renderTile({ isLoading: true });
  expect(screen.getByRole("status")).toBeInTheDocument();
  expect(screen.queryByText("Inhalt")).not.toBeInTheDocument();
});

test("shows the error branch", () => {
  renderTile({ isError: true });
  expect(screen.getByRole("alert")).toBeInTheDocument();
});

test("shows the empty branch with the given text", () => {
  renderTile({ isEmpty: true, emptyText: "Nichts da" });
  expect(screen.getByText("Nichts da")).toBeInTheDocument();
  expect(screen.queryByText("Inhalt")).not.toBeInTheDocument();
});
