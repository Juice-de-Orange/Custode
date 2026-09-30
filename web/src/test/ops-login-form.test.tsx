import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n/ops";
import { OpsLoginForm, type OpsLoginValues } from "../ops/components/ops-login-form";

function renderWithI18n(ui: ReactElement) {
  return render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);
}

describe("OpsLoginForm", () => {
  it("has no axe violations", async () => {
    const { container } = renderWithI18n(
      <OpsLoginForm onSubmit={() => {}} pending={false} error={null} />,
    );
    expect(await axe(container)).toHaveNoViolations();
  });

  it("submits e-mail, password and the mandatory TOTP code", () => {
    const onSubmit = vi.fn();
    renderWithI18n(<OpsLoginForm onSubmit={onSubmit} pending={false} error={null} />);

    fireEvent.change(screen.getByLabelText("E-Mail"), { target: { value: "op@custode.example" } });
    fireEvent.change(screen.getByLabelText("Passwort"), { target: { value: "s3cret" } });
    fireEvent.change(screen.getByLabelText("2FA-Code"), { target: { value: "123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Anmelden" }));

    expect(onSubmit).toHaveBeenCalledWith<[OpsLoginValues]>({
      email: "op@custode.example",
      password: "s3cret",
      totp_code: "123456",
    });
  });

  it("shows the error message and disables submit while pending", () => {
    renderWithI18n(<OpsLoginForm onSubmit={() => {}} pending={true} error="ops.login.error" />);
    expect(screen.getByRole("alert")).toHaveTextContent("falsch");
    expect(screen.getByRole("button", { name: "Anmelden" })).toBeDisabled();
  });
});
