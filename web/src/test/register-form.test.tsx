import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { RegisterForm } from "../components/register-form";
import { i18n } from "../i18n";

function fill(name: string, password: string, confirm: string) {
  fireEvent.change(screen.getByLabelText("Anzeigename"), { target: { value: name } });
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "max@b.de" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: password } });
  fireEvent.change(screen.getByLabelText("Passwort bestätigen"), { target: { value: confirm } });
}

test("submits the values when both passwords match", () => {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <RegisterForm onSubmit={onSubmit} pending={false} error={null} />
    </I18nProvider>,
  );
  fill("Mira", "ein-langes-passwort", "ein-langes-passwort");
  fireEvent.click(screen.getByRole("button", { name: "Registrieren" }));
  expect(onSubmit).toHaveBeenCalledWith({
    email: "max@b.de",
    password: "ein-langes-passwort",
    display_name: "Mira",
  });
});

test("does not submit and shows an alert when the passwords differ", () => {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <RegisterForm onSubmit={onSubmit} pending={false} error={null} />
    </I18nProvider>,
  );
  fill("Mira", "ein-langes-passwort", "anderes-passwort");
  fireEvent.click(screen.getByRole("button", { name: "Registrieren" }));
  expect(onSubmit).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("stimmen nicht überein");
});
