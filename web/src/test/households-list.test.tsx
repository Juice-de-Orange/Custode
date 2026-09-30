import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import type { HouseholdSummary } from "../api/types.gen";
import { HouseholdsList } from "../components/households-list";
import { i18n } from "../i18n";

const HOUSEHOLDS: HouseholdSummary[] = [
  { household_id: "h1", name: "Familie Berg", role: "admin" },
  { household_id: "h2", name: "WG Anton", role: "member" },
];

test("shows the empty state when there are no households", () => {
  render(
    <I18nProvider i18n={i18n}>
      <HouseholdsList households={[]} activeId={null} onSwitch={vi.fn()} pendingId={null} />
    </I18nProvider>,
  );
  expect(screen.getByText("Du gehörst noch keinem Haushalt an.")).toBeInTheDocument();
});

test("marks the active household and offers switching for the others", () => {
  const onSwitch = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <HouseholdsList households={HOUSEHOLDS} activeId="h1" onSwitch={onSwitch} pendingId={null} />
    </I18nProvider>,
  );
  expect(screen.getByText("Familie Berg")).toBeInTheDocument();
  expect(screen.getByText("WG Anton")).toBeInTheDocument();
  // The active household is flagged, not switchable; only the other one has a button.
  expect(screen.getByText("Aktiv")).toBeInTheDocument();
  const switchButtons = screen.getAllByRole("button", { name: "Wechseln" });
  expect(switchButtons).toHaveLength(1);
  fireEvent.click(switchButtons[0]);
  expect(onSwitch).toHaveBeenCalledWith("h2");
});
