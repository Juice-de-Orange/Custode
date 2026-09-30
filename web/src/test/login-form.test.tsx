import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { LoginForm } from "../components/login-form";
import { i18n } from "../i18n";

type Props = Parameters<typeof LoginForm>[0];

function renderForm(overrides: Partial<Props> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <LoginForm
        onSubmit={onSubmit}
        pending={false}
        totpRequired={false}
        error={null}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("renders email and password fields", () => {
  renderForm();
  expect(screen.getByLabelText("E-Mail")).toBeInTheDocument();
  expect(screen.getByLabelText("Passwort")).toBeInTheDocument();
});

test("submits the entered credentials", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "a@b.de" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "ein-langes-passwort" } });
  fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));
  expect(onSubmit).toHaveBeenCalledWith({
    email: "a@b.de",
    password: "ein-langes-passwort",
    totp_code: undefined,
  });
});

test("shows the TOTP field and verify label when required", () => {
  renderForm({ totpRequired: true });
  expect(screen.getByLabelText("Authenticator-Code")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Bestätigen" })).toBeInTheDocument();
});

test("shows the error message", () => {
  renderForm({ error: "auth.error.credentials" });
  expect(screen.getByRole("alert")).toHaveTextContent("E-Mail oder Passwort falsch.");
});

test("shows a passkey button when supported and calls onPasskey", () => {
  const onPasskey = vi.fn();
  renderForm({ onPasskey, passkeySupported: true });
  fireEvent.click(screen.getByRole("button", { name: "Mit Passkey anmelden" }));
  expect(onPasskey).toHaveBeenCalledOnce();
});

test("hides the passkey button when unsupported", () => {
  renderForm({ onPasskey: vi.fn(), passkeySupported: false });
  expect(screen.queryByRole("button", { name: "Mit Passkey anmelden" })).toBeNull();
});

test("switches to a recovery code and submits it instead of a TOTP code", () => {
  const { onSubmit } = renderForm({ totpRequired: true });
  fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "a@b.de" } });
  fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "ein-langes-passwort" } });
  fireEvent.click(screen.getByRole("button", { name: "Code verloren? Recovery-Code verwenden" }));
  fireEvent.change(screen.getByLabelText("Recovery-Code"), { target: { value: "abcd1234" } });
  fireEvent.click(screen.getByRole("button", { name: "Bestätigen" }));
  expect(onSubmit).toHaveBeenCalledWith({
    email: "a@b.de",
    password: "ein-langes-passwort",
    recovery_code: "abcd1234",
  });
});
