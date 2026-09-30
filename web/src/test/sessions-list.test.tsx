import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { SessionsList } from "../components/sessions-list";
import { i18n } from "../i18n";

type Props = Parameters<typeof SessionsList>[0];

function renderList(overrides: Partial<Props> = {}) {
  const onRevoke = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <SessionsList
        sessions={[]}
        loading={false}
        isError={false}
        revokePendingId={null}
        onRevoke={onRevoke}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onRevoke };
}

const CURRENT = {
  family_id: "fam-1",
  device_label: "MacBook",
  user_agent: null,
  last_used_at: "2026-06-19T10:00:00Z",
  current: true,
};
const OTHER = {
  family_id: "fam-2",
  device_label: "",
  user_agent: "Firefox",
  last_used_at: "2026-06-18T10:00:00Z",
  current: false,
};

test("shows the loading state", () => {
  renderList({ loading: true });
  expect(screen.getByRole("status")).toBeInTheDocument();
});

test("shows the empty state", () => {
  renderList();
  expect(screen.getByText("Keine aktiven Sitzungen.")).toBeInTheDocument();
});

test("shows the error state", () => {
  renderList({ isError: true });
  expect(screen.getByRole("alert")).toHaveTextContent("Etwas ist schiefgelaufen.");
});

test("lists sessions and badges the current device", () => {
  renderList({ sessions: [CURRENT, OTHER] });
  expect(screen.getByText("MacBook")).toBeInTheDocument();
  expect(screen.getByText("Firefox")).toBeInTheDocument(); // falls back to user_agent
  expect(screen.getByText("Dieses Gerät")).toBeInTheDocument();
});

test("revokes a session after confirmation", () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { onRevoke } = renderList({ sessions: [OTHER] });
  fireEvent.click(screen.getByRole("button", { name: "Abmelden" }));
  expect(onRevoke).toHaveBeenCalledWith("fam-2");
});

test("does not revoke when confirmation is cancelled", () => {
  vi.spyOn(window, "confirm").mockReturnValue(false);
  const { onRevoke } = renderList({ sessions: [OTHER] });
  fireEvent.click(screen.getByRole("button", { name: "Abmelden" }));
  expect(onRevoke).not.toHaveBeenCalled();
});
