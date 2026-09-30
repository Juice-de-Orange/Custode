import { Trans, useLingui } from "@lingui/react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";

import { useSession } from "../auth/session";
import { Button } from "../components/button";
import { StepTimer } from "../components/step-timer";
import { ErrorState, LoadingState } from "../components/states";
import { findDurationMinutes, parseSteps, scaleLine } from "../lib/cook";
import { useRecipe } from "../recipes/queries";
import { useWakeLock } from "../recipes/useWakeLock";

// Full-screen cook mode (T1): one step in focus, large touch targets, screen kept awake, a tap-timer
// when a step mentions a duration, and portion scaling of the ingredient quantities.
export function RecipeCookPage() {
  const navigate = useNavigate();
  const { i18n } = useLingui();
  const params = useParams({ strict: false }) as { id: string };
  const { data: session, isLoading: sessionLoading } = useSession();
  const recipe = useRecipe(params.id);
  const [stepIndex, setStepIndex] = useState(0);
  const [scale, setScale] = useState(1);

  useWakeLock(!sessionLoading && session !== null);

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  const steps = useMemo(() => (recipe.data ? parseSteps(recipe.data.steps_md) : []), [recipe.data]);

  if (sessionLoading || session === null || recipe.isLoading) return <LoadingState />;
  if (recipe.isError || !recipe.data) {
    return (
      <div className="p-6">
        <ErrorState />
      </div>
    );
  }

  const r = recipe.data;
  const scaledServings = Math.round((r.servings || 1) * scale);
  const currentStep = steps[stepIndex] ?? "";
  const duration = findDurationMinutes(currentStep);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-kalk pb-safe-b pt-safe-t text-tinte dark:bg-nacht dark:text-kalk">
      <header className="flex items-center justify-between gap-4 border-b border-stein/30 px-6 py-4">
        <span className="font-display text-lg">{r.title}</span>
        <button
          type="button"
          onClick={() => navigate({ to: "/recipes/$id", params: { id: params.id } })}
          className="rounded-md border border-stein/40 px-4 py-2 text-sm hover:bg-stein/10 dark:hover:bg-kalk/10"
        >
          <Trans id="cook.exit" />
        </button>
      </header>

      <div className="flex flex-1 flex-col gap-8 overflow-y-auto px-6 py-8 sm:flex-row">
        <main className="flex flex-1 flex-col">
          {steps.length > 0 ? (
            <>
              <p className="text-sm text-stein-text">
                <Trans id="cook.step" /> {stepIndex + 1} / {steps.length}
              </p>
              <p className="mt-4 flex-1 text-2xl leading-relaxed sm:text-3xl">{currentStep}</p>
              {duration ? (
                <div className="mt-6">
                  <StepTimer minutes={duration} />
                </div>
              ) : null}
              <div className="mt-8 flex gap-3">
                <Button
                  type="button"
                  disabled={stepIndex === 0}
                  onClick={() => setStepIndex((index) => index - 1)}
                  className="flex-1 justify-center py-4 text-lg disabled:opacity-40"
                >
                  <Trans id="cook.prev" />
                </Button>
                <Button
                  type="button"
                  disabled={stepIndex >= steps.length - 1}
                  onClick={() => setStepIndex((index) => index + 1)}
                  className="flex-1 justify-center py-4 text-lg disabled:opacity-40"
                >
                  <Trans id="cook.next" />
                </Button>
              </div>
            </>
          ) : (
            <p className="text-lg text-stein-text">
              <Trans id="cook.noSteps" />
            </p>
          )}
        </main>

        <aside className="sm:w-64 sm:shrink-0">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-display text-lg">
              <Trans id="recipe.ingredients" />
            </h2>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setScale((value) => Math.max(0.25, value - 0.5))}
                aria-label={i18n._("cook.fewer")}
                className="h-10 w-10 rounded-md border border-stein/40 text-xl hover:bg-stein/10 dark:hover:bg-kalk/10"
              >
                −
              </button>
              <span className="min-w-10 text-center tabular-nums" aria-label={i18n._("cook.servings")}>
                {scaledServings}
              </span>
              <button
                type="button"
                onClick={() => setScale((value) => value + 0.5)}
                aria-label={i18n._("cook.more")}
                className="h-10 w-10 rounded-md border border-stein/40 text-xl hover:bg-stein/10 dark:hover:bg-kalk/10"
              >
                +
              </button>
            </div>
          </div>
          <ul className="mt-3 space-y-2 text-tinte dark:text-kalk">
            {r.ingredients.map((line, index) => (
              <li key={index}>{scaleLine(line.raw_text, scale)}</li>
            ))}
          </ul>
        </aside>
      </div>
    </div>
  );
}
