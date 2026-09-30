import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { axe } from "vitest-axe";

import { i18n } from "../i18n/ops";
import { BannerForm } from "../ops/components/banner-form";

function renderWithI18n(ui: ReactElement) {
  return render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);
}

describe("BannerForm", () => {
  it("has no axe violations", async () => {
    const { container } = renderWithI18n(<BannerForm onSubmit={() => {}} pending={false} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  it("submits message + level and clears the message", () => {
    const onSubmit = vi.fn();
    renderWithI18n(<BannerForm onSubmit={onSubmit} pending={false} />);

    const message = screen.getByLabelText("Nachricht") as HTMLInputElement;
    fireEvent.change(message, { target: { value: "Wartung heute 22 Uhr" } });
    fireEvent.change(screen.getByLabelText("Stufe"), { target: { value: "warning" } });
    fireEvent.click(screen.getByRole("button", { name: "Anlegen" }));

    expect(onSubmit).toHaveBeenCalledWith({ message: "Wartung heute 22 Uhr", level: "warning" });
    expect(message.value).toBe("");
  });

  it("does not submit an empty message", () => {
    const onSubmit = vi.fn();
    renderWithI18n(<BannerForm onSubmit={onSubmit} pending={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Anlegen" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
