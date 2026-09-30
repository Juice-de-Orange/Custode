import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { Home, ShoppingCart } from "lucide-react";
import { expect, test, vi } from "vitest";

import { CommandDialog, type Command } from "../components/command-palette";
import { i18n } from "../i18n";

// Interaction contract for the ⌘K palette's combobox (the router-free core). Keyboard drives
// selection while focus stays on the input (aria-activedescendant pattern).
function renderDialog(commands: Command[]) {
  const onOpenChange = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <CommandDialog open onOpenChange={onOpenChange} commands={commands} />
    </I18nProvider>,
  );
  return { onOpenChange };
}

const CMDS = (runHeute = () => {}, runEinkauf = () => {}): Command[] => [
  { id: "a", label: "Heute", hint: "Alltag", icon: Home, run: runHeute },
  { id: "b", label: "Einkauf", hint: "Alltag", icon: ShoppingCart, run: runEinkauf },
];

test("filters commands by query", () => {
  renderDialog(CMDS());
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "eink" } });
  expect(screen.getByRole("option", { name: /Einkauf/ })).toBeInTheDocument();
  expect(screen.queryByRole("option", { name: /Heute/ })).not.toBeInTheDocument();
});

test("Enter runs the active (first) command and closes the palette", () => {
  const run = vi.fn();
  const { onOpenChange } = renderDialog(CMDS(run));
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "Enter" });
  expect(run).toHaveBeenCalledTimes(1);
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test("ArrowDown moves the active option before Enter runs it", () => {
  const runEinkauf = vi.fn();
  renderDialog(CMDS(() => {}, runEinkauf));
  const input = screen.getByRole("combobox");
  fireEvent.keyDown(input, { key: "ArrowDown" });
  fireEvent.keyDown(input, { key: "Enter" });
  expect(runEinkauf).toHaveBeenCalledTimes(1);
});

test("clicking an option runs it and closes the palette", () => {
  const runEinkauf = vi.fn();
  const { onOpenChange } = renderDialog(CMDS(() => {}, runEinkauf));
  fireEvent.click(screen.getByRole("option", { name: /Einkauf/ }));
  expect(runEinkauf).toHaveBeenCalledTimes(1);
  expect(onOpenChange).toHaveBeenCalledWith(false);
});

test("no matches hides the listbox and shows the empty label", () => {
  renderDialog(CMDS());
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzzz" } });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  // "Keine Treffer" appears twice by design: the visible <p> and the sr-only status region.
  expect(screen.getAllByText(i18n._("command.empty"))).toHaveLength(2);
});

test("announces the result count and the empty state via a polite status region (WCAG 4.1.3)", () => {
  renderDialog(CMDS());
  const status = screen.getByRole("status");
  expect(status).toHaveTextContent(i18n._("command.results", { count: 2 }));
  fireEvent.change(screen.getByRole("combobox"), { target: { value: "zzzz" } });
  expect(screen.getByRole("status")).toHaveTextContent(i18n._("command.empty"));
});
