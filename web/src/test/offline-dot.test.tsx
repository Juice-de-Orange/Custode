import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { axe } from "vitest-axe";

import { OfflineDot } from "../components/offline-dot";
import { i18n } from "../i18n";

// The quiet global offline pill (UX_KONZEPT: "leise, nie Modal"): invisible online, a
// role=status hint offline, gone again on reconnect.

function setOnline(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", { value, configurable: true });
}

afterEach(() => setOnline(true));

test("OfflineDot appears offline, disappears online, no axe violations", async () => {
  const { container } = render(
    <I18nProvider i18n={i18n}>
      <OfflineDot />
    </I18nProvider>,
  );
  expect(screen.queryByRole("status")).toBeNull();

  setOnline(false);
  fireEvent(window, new Event("offline"));
  expect(screen.getByRole("status")).toHaveTextContent("Offline");
  expect(await axe(container)).toHaveNoViolations();

  setOnline(true);
  fireEvent(window, new Event("online"));
  expect(screen.queryByRole("status")).toBeNull();
});
