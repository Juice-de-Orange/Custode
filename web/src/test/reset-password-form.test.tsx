import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ResetPasswordForm } from "../components/reset-password-form";
import { i18n } from "../i18n";

type Props = Parameters<typeof ResetPasswordForm>[0];

function renderForm(overrides: Partial<Props> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <ResetPasswordForm onSubmit={onSubmit} pending={false} error={null} done={false} {...overrides} />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("submits the new password when both fields match", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "ein-langes-passwort" } });
  fireEvent.change(screen.getByLabelText("Passwort bestätigen"), {
    target: { value: "ein-langes-passwort" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Passwort speichern" }));
  expect(onSubmit).toHaveBeenCalledWith("ein-langes-passwort");
});

test("blocks submit and warns on mismatch", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "passwort-eins" } });
  fireEvent.change(screen.getByLabelText("Passwort bestätigen"), {
    target: { value: "passwort-zwei" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Passwort speichern" }));
  expect(onSubmit).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("Die Passwörter stimmen nicht überein.");
});

test("shows a server error", () => {
  renderForm({ error: "auth.reset.invalid" });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Link ungültig oder abgelaufen. Bitte fordere einen neuen an.",
  );
});

test("shows a confirmation when done", () => {
  renderForm({ done: true });
  expect(screen.getByRole("status")).toHaveTextContent(
    "Passwort geändert. Du kannst dich jetzt anmelden.",
  );
});
