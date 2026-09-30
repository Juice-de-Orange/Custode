import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { UpdateToast } from "../components/pwa-update-toast";
import { i18n } from "../i18n";

// The presentational half of the PWA update prompt (ADR-0078) — rendered without the
// build-time virtual:pwa-register module, so it tests like any other component.
test("UpdateToast announces, fires its callbacks and has no axe violations", async () => {
  const onReload = vi.fn();
  const onDismiss = vi.fn();
  const { container } = render(
    <I18nProvider i18n={i18n}>
      <UpdateToast onReload={onReload} onDismiss={onDismiss} />
    </I18nProvider>,
  );

  expect(screen.getByRole("status")).toHaveTextContent("Neue Version verfügbar.");
  fireEvent.click(screen.getByRole("button", { name: "Neu laden" }));
  fireEvent.click(screen.getByRole("button", { name: "Später" }));
  expect(onReload).toHaveBeenCalledTimes(1);
  expect(onDismiss).toHaveBeenCalledTimes(1);

  expect(await axe(container)).toHaveNoViolations();
});
