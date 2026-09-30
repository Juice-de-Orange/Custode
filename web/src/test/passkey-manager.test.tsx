import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { PasskeyManager } from "../components/passkey-manager";
import { i18n } from "../i18n";

type Props = Parameters<typeof PasskeyManager>[0];

function renderPM(overrides: Partial<Props> = {}) {
  const onAdd = vi.fn();
  const onDelete = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <PasskeyManager
        passkeys={[]}
        loading={false}
        isError={false}
        supported={true}
        error={null}
        addPending={false}
        deletePendingId={null}
        onAdd={onAdd}
        onDelete={onDelete}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onAdd, onDelete };
}

const PASSKEY = {
  id: "pk-1",
  name: "MacBook",
  created_at: "2026-06-01T10:00:00Z",
  last_used_at: null,
};

test("shows the loading state", () => {
  renderPM({ loading: true });
  expect(screen.getByRole("status")).toBeInTheDocument();
});

test("shows the empty state when there are no passkeys", () => {
  renderPM();
  expect(screen.getByText("Noch keine Passkeys hinterlegt.")).toBeInTheDocument();
});

test("shows the error state when the list failed to load", () => {
  renderPM({ isError: true });
  expect(screen.getByRole("alert")).toHaveTextContent("Etwas ist schiefgelaufen.");
});

test("lists passkeys with their name", () => {
  renderPM({ passkeys: [PASSKEY] });
  expect(screen.getByText("MacBook")).toBeInTheDocument();
});

test("adds a passkey with the entered name", () => {
  const { onAdd } = renderPM();
  fireEvent.change(screen.getByLabelText("Name des Geräts"), { target: { value: "MacBook" } });
  fireEvent.click(screen.getByRole("button", { name: "Passkey hinzufügen" }));
  expect(onAdd).toHaveBeenCalledWith("MacBook");
});

test("deletes a passkey after confirmation", () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { onDelete } = renderPM({ passkeys: [PASSKEY] });
  fireEvent.click(screen.getByRole("button", { name: "Entfernen" }));
  expect(onDelete).toHaveBeenCalledWith("pk-1");
});

test("disables adding when passkeys are unsupported", () => {
  renderPM({ supported: false });
  expect(screen.getByRole("button", { name: "Passkey hinzufügen" })).toBeDisabled();
  expect(screen.getByText("Dieser Browser unterstützt keine Passkeys.")).toBeInTheDocument();
});
