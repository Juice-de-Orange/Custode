import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ChildCreateForm } from "../components/child-create-form";
import { i18n } from "../i18n";

type Props = Parameters<typeof ChildCreateForm>[0];

function renderForm(overrides: Partial<Props> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <ChildCreateForm
        onSubmit={onSubmit}
        pending={false}
        error={null}
        createdName={null}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("submits the child fields", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Name des Kindes"), { target: { value: "Mia" } });
  fireEvent.change(screen.getByLabelText("Benutzername"), { target: { value: "mia" } });
  fireEvent.change(screen.getByLabelText("PIN (4-6 Ziffern)"), { target: { value: "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "Kind anlegen" }));
  expect(onSubmit).toHaveBeenCalledWith({ display_name: "Mia", username: "mia", pin: "1234" });
});

test("shows an error", () => {
  renderForm({ error: "child.error.username" });
  expect(screen.getByRole("alert")).toHaveTextContent("Benutzername bereits vergeben.");
});

test("confirms the created child", () => {
  renderForm({ createdName: "mia" });
  expect(screen.getByRole("status")).toHaveTextContent("mia");
});
