import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { ProfileForm } from "../components/profile-form";
import { i18n } from "../i18n";

type Props = Parameters<typeof ProfileForm>[0];

function renderForm(overrides: Partial<Props> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <ProfileForm
        initial={{ display_name: "Tester", work_hours: "", dietary: [] }}
        onSubmit={onSubmit}
        pending={false}
        error={null}
        saved={false}
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("submits the edited values and parses the dietary list", () => {
  const { onSubmit } = renderForm({
    initial: { display_name: "Tester", work_hours: "Mo-Fr", dietary: ["vegan"] },
  });
  fireEvent.change(screen.getByLabelText("Anzeigename"), { target: { value: "Neu" } });
  fireEvent.change(screen.getByLabelText("Ernährung/Allergien (Komma-getrennt)"), {
    target: { value: "vegan, glutenfrei" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Speichern" }));
  expect(onSubmit).toHaveBeenCalledWith({
    display_name: "Neu",
    work_hours: "Mo-Fr",
    dietary: ["vegan", "glutenfrei"],
  });
});

test("shows a conflict error", () => {
  renderForm({ error: "profile.error.conflict" });
  expect(screen.getByRole("alert")).toHaveTextContent("Profil wurde anderswo geändert");
});

test("confirms after a save", () => {
  renderForm({ saved: true });
  expect(screen.getByRole("status")).toHaveTextContent("Profil gespeichert.");
});
