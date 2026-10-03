import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { axe } from "vitest-axe";

import { LanguageSection } from "../components/language-section";
import { i18n } from "../i18n";
import { getLocalePref, setLocalePref } from "../lib/locale";

afterEach(() => setLocalePref(null));

function renderSection() {
  const onChanged = vi.fn();
  const view = render(
    <I18nProvider i18n={i18n}>
      <LanguageSection onChanged={onChanged} />
    </I18nProvider>,
  );
  return { onChanged, ...view };
}

test("starts on 'same as browser' and has no axe violations", async () => {
  const { container } = renderSection();
  expect(screen.getByLabelText("Sprache der Oberfläche")).toHaveValue("auto");
  expect(await axe(container)).toHaveNoViolations();
});

test("choosing English stores the choice and asks for the reload", () => {
  const { onChanged } = renderSection();
  fireEvent.change(screen.getByLabelText("Sprache der Oberfläche"), { target: { value: "en" } });
  expect(getLocalePref()).toBe("en");
  expect(onChanged).toHaveBeenCalledOnce();
});

test("going back to the browser language forgets the stored choice", () => {
  setLocalePref("en");
  const { onChanged } = renderSection();
  expect(screen.getByLabelText("Sprache der Oberfläche")).toHaveValue("en");
  fireEvent.change(screen.getByLabelText("Sprache der Oberfläche"), { target: { value: "auto" } });
  expect(getLocalePref()).toBeNull();
  expect(onChanged).toHaveBeenCalledOnce();
});
