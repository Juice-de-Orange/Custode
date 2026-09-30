import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import { i18n } from "../i18n";

vi.mock("../tasks/queries", () => ({
  useRooms: vi.fn(),
  useTaskTemplates: vi.fn(),
  useApplyPreset: vi.fn(),
}));

import { OnboardingPresets } from "../components/preset-picker";
import { useApplyPreset, useRooms, useTaskTemplates } from "../tasks/queries";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ok = (data: unknown) => ({ data, isLoading: false, isError: false }) as any;
const mutate = vi.fn();

function renderPicker() {
  render(
    <I18nProvider i18n={i18n}>
      <OnboardingPresets />
    </I18nProvider>,
  );
}

beforeEach(() => {
  mutate.mockReset();
  vi.mocked(useRooms).mockReturnValue(ok([]));
  vi.mocked(useTaskTemplates).mockReturnValue(ok([]));
  vi.mocked(useApplyPreset).mockReturnValue({ mutate, isPending: false, isError: false } as never);
});

test("offers the three presets on an empty household", () => {
  renderPicker();
  expect(screen.getByRole("region", { name: "Schnellstart" })).toBeInTheDocument();
  expect(screen.getByText("Solo")).toBeInTheDocument();
  expect(screen.getByText("Familie")).toBeInTheDocument();
  expect(screen.getByText("WG")).toBeInTheDocument();
  expect(screen.getByText("5 Räume · 8 Aufgaben")).toBeInTheDocument(); // family summary, ICU plural
});

test("applying a preset seeds it via the mutation", () => {
  renderPicker();
  const buttons = screen.getAllByRole("button", { name: "Übernehmen" });
  fireEvent.click(buttons[0]); // solo
  expect(mutate).toHaveBeenCalledTimes(1);
  expect(mutate.mock.calls[0][0]).toMatchObject({ id: "solo" });
});

test("hides once the household already has rooms", () => {
  vi.mocked(useRooms).mockReturnValue(ok([{ id: "r1" }]));
  renderPicker();
  expect(screen.queryByRole("region", { name: "Schnellstart" })).not.toBeInTheDocument();
});

test("hides once the household already has task templates", () => {
  vi.mocked(useTaskTemplates).mockReturnValue(ok([{ id: "t1" }]));
  renderPicker();
  expect(screen.queryByText("Solo")).not.toBeInTheDocument();
});
