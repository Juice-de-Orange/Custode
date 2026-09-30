import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { StarterPicker } from "../components/starter-picker";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import type { StarterRecipe } from "../lib/starters";
import { useCreateRecipe, useRecipes } from "../recipes/queries";

// Recipe gallery (KONZEPT §5.2). Cards link to the detail page; "new" opens the editor.
// Auth-gated like the other protected routes.
export function RecipesPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const recipes = useRecipes();
  const create = useCreateRecipe();

  const handleAddStarter = (starter: StarterRecipe) => {
    create.mutate({
      title: starter.title,
      servings: starter.servings,
      steps_md: starter.steps_md,
      tags: starter.tags,
      ingredients: starter.ingredients.map((raw_text) => ({ raw_text })),
    });
  };

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || session === null) return <LoadingState />;

  return (
    <section aria-labelledby="recipes-heading" className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h1 id="recipes-heading" className="font-display text-2xl">
          <Trans id="recipe.section" />
        </h1>
        <div className="flex shrink-0 gap-2">
          <Button asChild variant="secondary">
            <Link to="/recipes/import">
              <Trans id="recipe.import.link" />
            </Link>
          </Button>
          <Button asChild>
            <Link to="/recipes/new">
              <Trans id="recipe.new" />
            </Link>
          </Button>
        </div>
      </div>

      {recipes.isLoading ? (
        <LoadingState />
      ) : recipes.isError ? (
        <ErrorState />
      ) : (
        <>
          {recipes.data && recipes.data.length > 0 ? (
            <ul className="grid gap-4 sm:grid-cols-2">
              {recipes.data.map((recipe) => (
                <li key={recipe.id}>
                  <Link
                    to="/recipes/$id"
                    params={{ id: recipe.id }}
                    className="block rounded-lg border border-stein/30 p-4 transition-colors hover:border-laurus hover:bg-stein/5"
                  >
                    {recipe.has_photo ? (
                      <img
                        src={`/v1/recipes/${recipe.id}/photo`}
                        alt=""
                        className="mb-3 h-32 w-full rounded object-cover"
                      />
                    ) : null}
                    <span className="font-display text-lg text-tinte dark:text-kalk">{recipe.title}</span>
                    {recipe.tags.length > 0 ? (
                      <span className="mt-1 block text-sm text-stein-text">
                        {recipe.tags.join(" · ")}
                      </span>
                    ) : null}
                    {recipe.last_cooked_at ? (
                      <span className="mt-1 block text-xs text-laurus dark:text-laurus-dark">
                        {i18n._("recipe.lastCooked")}{" "}
                        {new Date(recipe.last_cooked_at).toLocaleDateString()}
                      </span>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState>
              <Trans id="recipe.empty" />
            </EmptyState>
          )}

          {recipes.data && recipes.data.length > 0 ? (
            <details className="rounded-lg border border-stein/20 p-4">
              <summary className="cursor-pointer font-display text-lg text-tinte dark:text-kalk">
                <Trans id="starter.title" />
              </summary>
              <div className="mt-3">
                <StarterPicker onAdd={handleAddStarter} pending={create.isPending} />
              </div>
            </details>
          ) : (
            <section aria-labelledby="starters-heading" className="space-y-3">
              <h2 id="starters-heading" className="font-display text-lg">
                <Trans id="starter.title" />
              </h2>
              <StarterPicker onAdd={handleAddStarter} pending={create.isPending} />
            </section>
          )}
        </>
      )}
    </section>
  );
}
