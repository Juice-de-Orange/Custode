import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n/ops";
import { HealthView, SignupsView, UsageCountersView } from "../ops/components/kpi-views";

function renderWithI18n(ui: ReactElement) {
  return render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);
}

describe("KPI views", () => {
  it("renders usage counters with no axe violations", async () => {
    const { container } = renderWithI18n(
      <UsageCountersView usage={{ households: 4, users: 9, adult_members: 7, children: 2 }} />,
    );
    expect(screen.getByText("4")).toBeInTheDocument();
    expect(screen.getByText("Haushalte")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders the signup table with a caption and no axe violations", async () => {
    const { container } = renderWithI18n(
      <SignupsView
        daily={[
          { day: "2026-06-29", new_households: 1, new_users: 2 },
          { day: "2026-06-28", new_households: 0, new_users: 1 },
        ]}
      />,
    );
    expect(screen.getByText("2026-06-29")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders build/health info", async () => {
    const { container } = renderWithI18n(
      <HealthView health={{ env: "prod", app_version: "0.1.0", git_sha: "abc1234" }} />,
    );
    expect(screen.getByText("prod")).toBeInTheDocument();
    expect(screen.getByText("abc1234")).toBeInTheDocument();
    expect(await axe(container)).toHaveNoViolations();
  });
});
