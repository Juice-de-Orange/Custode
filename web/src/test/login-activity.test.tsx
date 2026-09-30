import { I18nProvider } from "@lingui/react";
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import { LoginActivity } from "../components/login-activity";
import { i18n } from "../i18n";

type Props = Parameters<typeof LoginActivity>[0];

function renderActivity(overrides: Partial<Props> = {}) {
  render(
    <I18nProvider i18n={i18n}>
      <LoginActivity events={[]} loading={false} isError={false} {...overrides} />
    </I18nProvider>,
  );
}

test("shows the loading state", () => {
  renderActivity({ loading: true });
  expect(screen.getByRole("status")).toBeInTheDocument();
});

test("shows the empty state", () => {
  renderActivity();
  expect(screen.getByText("Noch keine Anmeldungen.")).toBeInTheDocument();
});

test("shows the error state", () => {
  renderActivity({ isError: true });
  expect(screen.getByRole("alert")).toHaveTextContent("Etwas ist schiefgelaufen.");
});

test("renders success and failure entries with country code", () => {
  renderActivity({
    events: [
      { success: true, country_code: "AT", created_at: "2026-06-19T10:00:00Z" },
      { success: false, country_code: null, created_at: "2026-06-18T10:00:00Z" },
    ],
  });
  expect(screen.getByText("Erfolgreich")).toBeInTheDocument();
  expect(screen.getByText("Fehlgeschlagen")).toBeInTheDocument();
  expect(screen.getByText("AT")).toBeInTheDocument();
});
