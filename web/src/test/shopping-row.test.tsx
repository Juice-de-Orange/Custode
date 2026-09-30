import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { i18n } from "../i18n";
import { ShoppingRow } from "../routes/shopping";
import type { LocalItem } from "../shopping/db";
import type { useShoppingActions } from "../shopping/queries";

function makeItem(checked = false): LocalItem {
  return {
    id: "i1",
    list_id: "l1",
    label: "Milch",
    qty: null,
    unit: null,
    category: "Kühlregal",
    checked,
    source: "manual",
    notes: null,
    reserved_by: null,
    checked_by: null,
  };
}

function renderRow(checked = false) {
  const mutate = vi.fn();
  const actions = { mutate } as unknown as ReturnType<typeof useShoppingActions>;
  render(
    <I18nProvider i18n={i18n}>
      <ul>
        <ShoppingRow item={makeItem(checked)} actions={actions} me="u1" />
      </ul>
    </I18nProvider>,
  );
  return { mutate };
}

test("shows the label and toggles checked", () => {
  const { mutate } = renderRow(false);
  expect(screen.getByText("Milch")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox"));
  expect(mutate).toHaveBeenCalledWith({ type: "toggle", item: makeItem(false) });
});

test("removes the item", () => {
  const { mutate } = renderRow();
  fireEvent.click(screen.getByRole("button", { name: "Entfernen" }));
  expect(mutate).toHaveBeenCalledWith({ type: "delete", id: "i1" });
});

test("reserves the item as the current user", () => {
  const { mutate } = renderRow();
  fireEvent.click(screen.getByRole("button", { name: "Reservieren" }));
  expect(mutate).toHaveBeenCalledWith({ type: "reserve", item: makeItem(false), reservedBy: "u1" });
});
