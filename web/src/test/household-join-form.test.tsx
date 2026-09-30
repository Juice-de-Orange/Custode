import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { HouseholdJoinForm } from "../components/household-join-form";
import { i18n } from "../i18n";

test("submits the invite code", () => {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <HouseholdJoinForm onSubmit={onSubmit} pending={false} error={null} />
    </I18nProvider>,
  );
  fireEvent.change(screen.getByLabelText("Einladungs-Code"), { target: { value: "ABC123" } });
  fireEvent.click(screen.getByRole("button", { name: "Beitreten" }));
  expect(onSubmit).toHaveBeenCalledWith("ABC123");
});

test("shows the error message", () => {
  render(
    <I18nProvider i18n={i18n}>
      <HouseholdJoinForm onSubmit={vi.fn()} pending={false} error="household.error.code" />
    </I18nProvider>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Einladung ungültig");
});
