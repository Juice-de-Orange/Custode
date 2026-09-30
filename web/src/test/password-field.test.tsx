import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { PasswordField } from "../components/password-field";
import { i18n } from "../i18n";

test("toggles between hidden and revealed", () => {
  render(
    <I18nProvider i18n={i18n}>
      <PasswordField id="pw" label="Passwort" value="geheim" onChange={() => {}} />
    </I18nProvider>,
  );
  const input = screen.getByLabelText("Passwort");
  expect(input).toHaveAttribute("type", "password");

  fireEvent.click(screen.getByRole("button", { name: "Anzeigen" }));
  expect(input).toHaveAttribute("type", "text");

  // The same button now offers hiding again.
  fireEvent.click(screen.getByRole("button", { name: "Verbergen" }));
  expect(input).toHaveAttribute("type", "password");
});
