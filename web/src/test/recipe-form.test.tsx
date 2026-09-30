import { I18nProvider } from "@lingui/react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";

import { RecipeForm, type RecipeFormValues } from "../components/recipe-form";
import { i18n } from "../i18n";

const EMPTY: RecipeFormValues = { title: "", servings: 2, steps_md: "", tags: [], ingredients: [] };

function renderForm(overrides: Partial<Parameters<typeof RecipeForm>[0]> = {}) {
  const onSubmit = vi.fn();
  render(
    <I18nProvider i18n={i18n}>
      <RecipeForm
        initial={EMPTY}
        onSubmit={onSubmit}
        pending={false}
        error={null}
        submitLabel="recipe.create"
        {...overrides}
      />
    </I18nProvider>,
  );
  return { onSubmit };
}

test("submits the structured recipe fields", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Pasta" } });
  fireEvent.change(screen.getByLabelText("Portionen"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("Zutat 1"), { target: { value: "500g Mehl" } });
  fireEvent.change(screen.getByLabelText("Schritte (Markdown)"), { target: { value: "Kochen." } });
  fireEvent.change(screen.getByLabelText("Tags (Komma-getrennt)"), {
    target: { value: "schnell, vegan" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Rezept anlegen" }));
  expect(onSubmit).toHaveBeenCalledWith({
    title: "Pasta",
    servings: 4,
    steps_md: "Kochen.",
    tags: ["schnell", "vegan"],
    ingredients: ["500g Mehl"],
  });
});

test("adds and removes ingredient rows", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "Suppe" } });
  fireEvent.change(screen.getByLabelText("Zutat 1"), { target: { value: "Wasser" } });
  fireEvent.click(screen.getByRole("button", { name: "+ Zutat hinzufügen" }));
  fireEvent.change(screen.getByLabelText("Zutat 2"), { target: { value: "Salz" } });
  fireEvent.click(screen.getByRole("button", { name: "Rezept anlegen" }));
  expect(onSubmit).toHaveBeenCalledWith(
    expect.objectContaining({ ingredients: ["Wasser", "Salz"] }),
  );
});

test("drops blank ingredient lines", () => {
  const { onSubmit } = renderForm();
  fireEvent.change(screen.getByLabelText("Titel"), { target: { value: "X" } });
  fireEvent.click(screen.getByRole("button", { name: "Rezept anlegen" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ ingredients: [] }));
});

test("shows a conflict error", () => {
  renderForm({ error: "recipe.error.conflict" });
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Rezept wurde anderswo geändert. Bitte neu laden.",
  );
});
