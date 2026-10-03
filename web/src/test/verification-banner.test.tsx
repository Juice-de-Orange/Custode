import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { needsEmailVerification, VerificationBanner } from "../components/verification-banner";
import { i18n } from "../i18n";

type Props = Parameters<typeof VerificationBanner>[0];

function renderBanner(overrides: Partial<Props> = {}) {
  const onResend = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <VerificationBanner onResend={onResend} pending={false} sent={false} {...overrides} />
    </I18nProvider>,
  );
  return { onResend };
}

test("prompts to verify and resends on click", () => {
  const { onResend } = renderBanner();
  expect(screen.getByText("Bitte bestätige deine E-Mail-Adresse.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Bestätigungs-Mail erneut senden" }));
  expect(onResend).toHaveBeenCalledOnce();
});

test("confirms after a resend (no button)", () => {
  renderBanner({ sent: true });
  expect(screen.getByText("Bestätigungs-Mail gesendet.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Bestätigungs-Mail erneut senden" })).toBeNull();
});

test("only an account that has an e-mail address is asked to confirm it", () => {
  expect(needsEmailVerification({ email: "a@example.org", email_verified: false })).toBe(true);
  expect(needsEmailVerification({ email: "a@example.org", email_verified: true })).toBe(false);
  // A child account signs in with username + PIN and has no address to confirm.
  expect(needsEmailVerification({ email: null, email_verified: false })).toBe(false);
});
