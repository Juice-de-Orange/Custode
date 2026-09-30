import { Trans, useLingui } from "@lingui/react";
import { Link, useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { ProblemError, useSession } from "../auth/session";
import { CommentThread } from "../comments/thread";
import { Button } from "../components/button";
import { LinksPanel } from "../links/panel";
import { NutritionPanel } from "../components/nutrition-panel";
import { RecipeForm, type RecipeFormValues } from "../components/recipe-form";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import {
  useDeletePhoto,
  useDeleteRecipe,
  useRecipe,
  useRecipeNutrition,
  useUpdateRecipe,
  useUploadPhoto,
} from "../recipes/queries";

// Recipe detail: read view + inline structured editor (PATCH with If-Match -> 412 conflict) +
// soft-delete. Auth-gated.
export function RecipeDetailPage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  const params = useParams({ strict: false }) as { id: string };
  const { data: session, isLoading: sessionLoading } = useSession();
  const recipe = useRecipe(params.id);
  const nutrition = useRecipeNutrition(params.id);
  const update = useUpdateRecipe();
  const remove = useDeleteRecipe();
  const uploadPhoto = useUploadPhoto();
  const removePhoto = useDeletePhoto();
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || session === null || recipe.isLoading) return <LoadingState />;
  if (recipe.isError || !recipe.data) return <ErrorState />;

  const r = recipe.data;
  const safeSource = r.source_url && /^https?:\/\//i.test(r.source_url) ? r.source_url : null;

  const handleSave = (values: RecipeFormValues) => {
    setError(null);
    update.mutate(
      {
        id: params.id,
        etag: r.etag,
        update: {
          title: values.title,
          servings: values.servings,
          steps_md: values.steps_md,
          tags: values.tags,
          ingredients: values.ingredients.map((raw_text) => ({ raw_text })),
        },
      },
      {
        onSuccess: () => setEditing(false),
        onError: (err) =>
          setError(
            err instanceof ProblemError && err.slug === "precondition_failed"
              ? "recipe.error.conflict"
              : "state.error",
          ),
      },
    );
  };

  const handleDelete = () => {
    if (!window.confirm(i18n._("recipe.confirmDelete"))) return;
    remove.mutate(params.id, { onSuccess: () => navigate({ to: "/recipes" }) });
  };

  if (editing) {
    return (
      <section aria-labelledby="recipe-edit-heading" className="space-y-6">
        <h1 id="recipe-edit-heading" className="font-display text-2xl">
          <Trans id="recipe.editTitle" />
        </h1>
        <RecipeForm
          initial={{
            title: r.title,
            servings: r.servings,
            steps_md: r.steps_md,
            tags: r.tags,
            ingredients: r.ingredients.map((line) => line.raw_text),
          }}
          onSubmit={handleSave}
          pending={update.isPending}
          error={error}
          submitLabel="recipe.save"
        />
        <button
          type="button"
          onClick={() => {
            setEditing(false);
            setError(null);
          }}
          className="text-sm text-laurus dark:text-laurus-dark hover:underline"
        >
          <Trans id="recipe.cancel" />
        </button>
      </section>
    );
  }

  return (
    <section aria-labelledby="recipe-heading" className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <h1 id="recipe-heading" className="font-display text-2xl">
          {r.title}
        </h1>
        <div className="flex shrink-0 flex-wrap justify-end gap-2">
          <Button asChild>
            <Link to="/recipes/$id/cook" params={{ id: params.id }}>
              <Trans id="cook.open" />
            </Link>
          </Button>
          <Button onClick={() => setEditing(true)} variant="secondary">
            <Trans id="recipe.edit" />
          </Button>
          <Button onClick={handleDelete} disabled={remove.isPending} variant="danger">
            <Trans id="recipe.delete" />
          </Button>
        </div>
      </div>

      <p className="text-sm text-stein-text">
        <Trans id="recipe.servings" />: {r.servings}
      </p>
      {r.tags.length > 0 ? <p className="text-sm text-stein-text">{r.tags.join(" · ")}</p> : null}

      <div className="space-y-2">
        {r.has_photo ? (
          <img
            src={`/v1/recipes/${params.id}/photo?v=${r.version}`}
            alt={r.title}
            className="max-h-80 w-full rounded-lg object-cover"
          />
        ) : null}
        <div className="flex gap-4 text-sm">
          <label className="cursor-pointer text-laurus dark:text-laurus-dark hover:underline">
            <Trans id={r.has_photo ? "recipe.photoReplace" : "recipe.photoAdd"} />
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) uploadPhoto.mutate({ id: params.id, file });
                event.target.value = "";
              }}
            />
          </label>
          {r.has_photo ? (
            <button
              type="button"
              onClick={() => removePhoto.mutate(params.id)}
              disabled={removePhoto.isPending}
              className="text-stein-text hover:text-rost"
            >
              <Trans id="recipe.photoRemove" />
            </button>
          ) : null}
        </div>
        {uploadPhoto.isError ? (
          <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
            <Trans id="recipe.photoError" />
          </p>
        ) : null}
      </div>

      <div>
        <h2 className="font-display text-lg">
          <Trans id="recipe.ingredients" />
        </h2>
        {r.ingredients.length > 0 ? (
          <ul className="mt-2 list-inside list-disc space-y-1 text-tinte dark:text-kalk">
            {r.ingredients.map((line, index) => (
              <li key={index}>
                {line.raw_text}
                {line.ingredient_name ? (
                  <span className="ml-2 text-sm text-stein-text">→ {line.ingredient_name}</span>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>
            <Trans id="recipe.noIngredients" />
          </EmptyState>
        )}
      </div>

      {nutrition.data && nutrition.data.total > 0 ? (
        <div>
          <h2 className="font-display text-lg">
            <Trans id="nutrition.title" />
          </h2>
          <div className="mt-2">
            <NutritionPanel data={nutrition.data} />
          </div>
        </div>
      ) : null}

      {r.steps_md ? (
        <div>
          <h2 className="font-display text-lg">
            <Trans id="recipe.steps" />
          </h2>
          <p className="mt-2 whitespace-pre-wrap text-tinte dark:text-kalk">{r.steps_md}</p>
        </div>
      ) : null}

      {safeSource ? (
        <a
          href={safeSource}
          target="_blank"
          rel="noreferrer noopener"
          className="block text-sm text-laurus dark:text-laurus-dark hover:underline"
        >
          <Trans id="recipe.source" />
        </a>
      ) : null}

      {/* Links + comments on this recipe (KONZEPT §5.12, generic object panels). */}
      <div className="space-y-4 border-t border-stein/20 pt-4">
        <LinksPanel objectType="recipe" objectId={params.id} />
        <CommentThread objectType="recipe" objectId={params.id} />
      </div>

      <Link to="/recipes" className="block text-sm text-laurus dark:text-laurus-dark hover:underline">
        <Trans id="recipe.back" />
      </Link>
    </section>
  );
}
