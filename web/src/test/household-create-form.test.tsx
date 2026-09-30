import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { HouseholdCreateForm } from "../components/household-create-form";
import { i18n } from "../i18n";

test("submits the household name", () => {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <HouseholdCreateForm onSubmit={onSubmit} pending={false} error={null} />
    </I18nProvider>,
  );
  fireEvent.change(screen.getByLabelText("Haushaltsname"), { target: { value: "Familie Berg" } });
  fireEvent.click(screen.getByRole("button", { name: "Haushalt anlegen" }));
  expect(onSubmit).toHaveBeenCalledWith("Familie Berg");
});

test("shows the error message", () => {
  render(
    <I18nProvider i18n={i18n}>
      <HouseholdCreateForm onSubmit={vi.fn()} pending={false} error="state.error" />
    </I18nProvider>,
  );
  expect(screen.getByRole("alert")).toHaveTextContent("Etwas ist schiefgelaufen.");
});
