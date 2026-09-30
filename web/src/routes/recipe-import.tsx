import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { type FormEvent, useEffect, useState } from "react";

import { ProblemError, useSession } from "../auth/session";
import { Button } from "../components/button";
import { Field } from "../components/field";
import { RecipeForm, type RecipeFormValues } from "../components/recipe-form";
import { LoadingState } from "../components/states";
import { useCreateRecipe, useImportRecipe } from "../recipes/queries";

function importError(err: unknown): string {
  if (err instanceof ProblemError) {
    if (err.slug === "import_url_blocked") return "recipe.import.error.blocked";
    if (err.slug === "import_no_recipe") return "recipe.import.error.noRecipe";
    if (
      err.slug === "import_fetch_failed" ||
      err.slug === "import_too_large" ||
      err.slug === "import_too_many_redirects"
    ) {
      return "recipe.import.error.fetch";
    }
  }
  return "state.error";
}

// Import a recipe from a URL: enter URL -> server fetches (SSRF-guarded) + extracts a draft ->
// review/correct in the editor -> save via create. The draft is never persisted server-side.
export function RecipeImportPage() {
  const navigate = useNavigate();
  const { data: session, isLoading } = useSession();
  const importRecipe = useImportRecipe();
  const create = useCreateRecipe();
  const [url, setUrl] = useState("");
  const [draft, setDraft] = useState<RecipeFormValues | null>(null);
  const [sourceUrl, setSourceUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && session === null) navigate({ to: "/login" });
  }, [isLoading, session, navigate]);

  if (isLoading || session === null) return <LoadingState />;

  const handleImport = (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    importRecipe.mutate(url, {
      onSuccess: (res) => {
        setSourceUrl(res.source_url);
        setDraft({
          title: res.title,
          servings: res.servings,
          steps_md: res.steps_md,
          tags: res.tags,
          ingredients: res.ingredients.map((line) => line.raw_text),
        });
      },
      onError: (err) => setError(importError(err)),
    });
  };

  const handleSave = (values: RecipeFormValues) => {
    setError(null);
    create.mutate(
      {
        title: values.title,
        servings: values.servings,
        steps_md: values.steps_md,
        tags: values.tags,
        source_url: sourceUrl || null,
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

  if (draft) {
    return (
      <section aria-labelledby="recipe-import-heading" className="space-y-6">
        <h1 id="recipe-import-heading" className="font-display text-2xl">
          <Trans id="recipe.import.review" />
        </h1>
        <p className="text-sm text-stein-text">
          <Trans id="recipe.import.reviewHint" />
        </p>
        <RecipeForm
          initial={draft}
          onSubmit={handleSave}
          pending={create.isPending}
          error={error}
          submitLabel="recipe.create"
        />
        <button
          type="button"
          onClick={() => {
            setDraft(null);
            setError(null);
          }}
          className="text-sm text-laurus dark:text-laurus-dark hover:underline"
        >
          <Trans id="recipe.import.tryAnother" />
        </button>
      </section>
    );
  }

  return (
    <section aria-labelledby="recipe-import-heading" className="space-y-6">
      <h1 id="recipe-import-heading" className="font-display text-2xl">
        <Trans id="recipe.import.title" />
      </h1>
      <p className="text-sm text-stein-text">
        <Trans id="recipe.import.hint" />
      </p>
      <form onSubmit={handleImport} className="space-y-4" noValidate>
        <Field
          id="import-url"
          type="url"
          required
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://…"
          label={<Trans id="recipe.import.url" />}
        />
        {error ? (
          <p role="alert" className="text-sm text-bernstein">
            <Trans id={error} />
          </p>
        ) : null}
        <Button type="submit" disabled={importRecipe.isPending}>
          <Trans id="recipe.import.fetch" />
        </Button>
      </form>
      <Link to="/recipes" className="block text-sm text-laurus dark:text-laurus-dark hover:underline">
        <Trans id="recipe.back" />
      </Link>
    </section>
  );
}
