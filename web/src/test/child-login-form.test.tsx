import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ChildLoginForm } from "../components/child-login-form";
import { i18n } from "../i18n";

type Props = Parameters<typeof ChildLoginForm>[0];

function renderForm(overrides: Partial<Props> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <ChildLoginForm onSubmit={onSubmit} pending={false} error={null} {...overrides} />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("submits username and PIN", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Benutzername"), { target: { value: "mia" } });
  fireEvent.change(screen.getByLabelText("PIN (4-6 Ziffern)"), { target: { value: "1234" } });
  fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));
  expect(onSubmit).toHaveBeenCalledWith({ username: "mia", pin: "1234" });
});

test("shows an error", () => {
  renderForm({ error: "child.error.pin" });
  expect(screen.getByRole("alert")).toHaveTextContent("PIN falsch.");
});
