import { Trans, useLingui } from "@lingui/react";
import { X } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

export type RecipeFormValues = {
  title: string;
  servings: number;
  steps_md: string;
  tags: string[];
  ingredients: string[]; // raw_text lines (qty/unit parsing + canonical mapping land in S4/S5)
};

type RecipeFormProps = {
  initial: RecipeFormValues;
  onSubmit: (values: RecipeFormValues) => void;
  pending: boolean;
  error: string | null; // i18n key, or null
  submitLabel: string; // i18n key (create vs save)
};

const INPUT =
  "block w-full rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk " +
  "focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40";

// Structured recipe editor (KONZEPT §5.2). Ingredients are dynamic raw_text rows; the /recipes
// routes wire create vs. update (the latter with If-Match). Pure — trivially testable.
export function RecipeForm({ initial, onSubmit, pending, error, submitLabel }: RecipeFormProps) {
  const { i18n } = useLingui();
  const [title, setTitle] = useState(initial.title);
  const [servings, setServings] = useState(String(initial.servings));
  const [stepsMd, setStepsMd] = useState(initial.steps_md);
  const [tags, setTags] = useState(initial.tags.join(", "));
  const [ingredients, setIngredients] = useState<string[]>(
    initial.ingredients.length > 0 ? initial.ingredients : [""],
  );

  const setIngredient = (index: number, value: string) =>
    setIngredients((rows) => rows.map((row, i) => (i === index ? value : row)));
  const addIngredient = () => setIngredients((rows) => [...rows, ""]);
  const removeIngredient = (index: number) =>
    setIngredients((rows) => (rows.length > 1 ? rows.filter((_, i) => i !== index) : rows));

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({
      title,
      servings: Number(servings) || 1,
      steps_md: stepsMd,
      tags: tags
        .split(",")
        .map((tag) => tag.trim())
        .filter(Boolean),
      ingredients: ingredients.map((row) => row.trim()).filter(Boolean),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Field
        id="recipe-title"
        required
        value={title}
        onChange={(event) => setTitle(event.target.value)}
        label={<Trans id="recipe.title" />}
      />
      <Field
        id="recipe-servings"
        type="number"
        inputMode="numeric"
        min={1}
        value={servings}
        onChange={(event) => setServings(event.target.value)}
        label={<Trans id="recipe.servings" />}
      />

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-tinte dark:text-kalk">
          <Trans id="recipe.ingredients" />
        </legend>
        {ingredients.map((row, index) => (
          <div key={index} className="flex gap-2">
            <input
              aria-label={`${i18n._("recipe.ingredient")} ${index + 1}`}
              value={row}
              onChange={(event) => setIngredient(index, event.target.value)}
              className={INPUT}
            />
            <button
              type="button"
              onClick={() => removeIngredient(index)}
              aria-label={i18n._("recipe.removeIngredient")}
              className="flex shrink-0 items-center rounded-md border border-stein/40 px-3 hover:bg-stein/10 dark:border-stein/25 dark:hover:bg-kalk/10"
            >
              <X className="size-4" aria-hidden="true" />
            </button>
          </div>
        ))}
        <button type="button" onClick={addIngredient} className="text-sm text-laurus dark:text-laurus-dark hover:underline">
          <Trans id="recipe.addIngredient" />
        </button>
      </fieldset>

      <div className="space-y-1">
        <label htmlFor="recipe-steps" className="block text-sm font-medium text-tinte dark:text-kalk">
          <Trans id="recipe.steps" />
        </label>
        <textarea
          id="recipe-steps"
          rows={8}
          value={stepsMd}
          onChange={(event) => setStepsMd(event.target.value)}
          className={INPUT}
        />
      </div>

      <Field
        id="recipe-tags"
        value={tags}
        onChange={(event) => setTags(event.target.value)}
        label={<Trans id="recipe.tags" />}
      />

      {error ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending}>
        <Trans id={submitLabel} />
      </Button>
    </form>
  );
}
