import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { InstallCard } from "../components/install-app";
import { i18n } from "../i18n";

// The presentational install card (ADR-0078) in its three shapes: Chromium prompt, iOS manual
// steps, and the dismissible /today hint variant.

function renderCard(ui: React.ReactNode) {
  return render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);
}

test("prompt variant fires onInstall and has no axe violations", async () => {
  const onInstall = vi.fn();
  const { container } = renderCard(<InstallCard variant="prompt" onInstall={onInstall} />);
  fireEvent.click(screen.getByRole("button", { name: "Installieren" }));
  expect(onInstall).toHaveBeenCalledTimes(1);
  expect(await axe(container)).toHaveNoViolations();
});

test("ios variant shows the manual steps and has no axe violations", async () => {
  const { container } = renderCard(<InstallCard variant="ios" />);
  expect(screen.getByText(/Zum Home-Bildschirm/)).toBeInTheDocument();
  expect(screen.queryByRole("button")).toBeNull(); // no prompt, no dismiss → no buttons
  expect(await axe(container)).toHaveNoViolations();
});

test("dismissible hint variant fires onDismiss", async () => {
  const onDismiss = vi.fn();
  renderCard(<InstallCard variant="ios" onDismiss={onDismiss} />);
  fireEvent.click(screen.getByRole("button", { name: "Ausblenden" }));
  expect(onDismiss).toHaveBeenCalledTimes(1);
});
