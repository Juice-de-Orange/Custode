import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ForgotPasswordForm } from "../components/forgot-password-form";
import { i18n } from "../i18n";

type Props = Parameters<typeof ForgotPasswordForm>[0];

function renderForm(overrides: Partial<Props> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <ForgotPasswordForm onSubmit={onSubmit} pending={false} submitted={false} {...overrides} />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("submits the entered e-mail", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "a@b.de" } });
  fireEvent.click(screen.getByRole("button", { name: "Link anfordern" }));
  expect(onSubmit).toHaveBeenCalledWith("a@b.de");
});

test("shows a generic confirmation once submitted (no enumeration)", () => {
  renderForm({ submitted: true });
  expect(screen.getByRole("status")).toHaveTextContent(
    "Falls die Adresse existiert, haben wir einen Link zum Zurücksetzen geschickt.",
  );
  expect(screen.queryByRole("button", { name: "Link anfordern" })).toBeNull();
});
