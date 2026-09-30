import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import type { AuditLogEntry } from "../api/types.gen";
import { i18n } from "../i18n/ops";
import { OpsAuditList } from "../ops/components/ops-audit-list";

function renderWithI18n(ui: ReactElement) {
  return render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);
}

const ENTRY: AuditLogEntry = {
  id: "a-1",
  occurred_at: "2026-02-01T10:00:00Z",
  actor_type: "operator",
  actor_id: "op-1",
  action: "flag.changed",
  target_type: "flag",
  target_id: null,
  household_id: null,
  detail: { key: "marketplace", enabled: true },
  request_id: null,
};

const baseProps = {
  entries: [ENTRY],
  loading: false,
  isError: false,
  actions: ["flag.changed", "household.viewed"],
  action: "",
  onActionChange: () => {},
};

describe("OpsAuditList", () => {
  it("has no axe violations", async () => {
    const { container } = renderWithI18n(<OpsAuditList {...baseProps} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("renders an entry with its action and PII-free detail", () => {
    renderWithI18n(<OpsAuditList {...baseProps} />);
    // "flag.changed" appears both as a filter <option> and the entry <span>; scope to the entry.
    expect(screen.getByText("flag.changed", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText(/key: marketplace · enabled: true/)).toBeInTheDocument();
  });

  it("shows the empty state when there are no entries", () => {
    renderWithI18n(<OpsAuditList {...baseProps} entries={[]} />);
    expect(screen.getByText("Keine Audit-Einträge.")).toBeInTheDocument();
  });

  it("offers the distinct actions in the filter and reports changes", () => {
    const onActionChange = vi.fn();
    renderWithI18n(<OpsAuditList {...baseProps} onActionChange={onActionChange} />);
    const select = screen.getByLabelText("Aktion");
    expect(screen.getByRole("option", { name: "household.viewed" })).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "flag.changed" } });
    expect(onActionChange).toHaveBeenCalledWith("flag.changed");
  });
});
