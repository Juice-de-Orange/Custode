import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { ProblemError, useSession } from "../auth/session";
import { RecipeForm, type RecipeFormValues } from "../components/recipe-form";
import { LoadingState } from "../components/states";
import { useCreateRecipe } from "../recipes/queries";

const EMPTY: RecipeFormValues = {
  title: "",
  servings: 2,
  steps_md: "",
  tags: [],
  ingredients: [],
};

// Create a recipe via the structured editor, then jump to its detail page.
export function RecipeNewPage() {
  const navigate = useNavigate();
  const { data: session, isLoading } = useSession();
  const create = useCreateRecipe();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && session === null) navigate({ to: "/login" });
  }, [isLoading, session, navigate]);

  if (isLoading || session === null) return <LoadingState />;

  const handleSubmit = (values: RecipeFormValues) => {
    setError(null);
    create.mutate(
      {
        title: values.title,
        servings: values.servings,
        steps_md: values.steps_md,
        tags: values.tags,
        ingredients: values.ingredients.map((raw_text) => ({ raw_text })),
      },
      {
        onSuccess: (recipe) => navigate({ to: "/recipes/$id", params: { id: recipe.id } }),
        onError: (err) =>
          setError(
            err instanceof ProblemError && err.slug === "forbidden"
              ? "recipe.error.noHousehold"
              : "state.error",
          ),
      },
    );
  };

  return (
    <section aria-labelledby="recipe-new-heading" className="space-y-6">
      <h1 id="recipe-new-heading" className="font-display text-2xl">
        <Trans id="recipe.new" />
      </h1>
      <RecipeForm
        initial={EMPTY}
        onSubmit={handleSubmit}
        pending={create.isPending}
        error={error}
        submitLabel="recipe.create"
      />
      <Link to="/recipes" className="block text-sm text-laurus dark:text-laurus-dark hover:underline">
        <Trans id="recipe.back" />
      </Link>
    </section>
  );
}
