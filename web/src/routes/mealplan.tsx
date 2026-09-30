import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { CalendarClock, Check, CookingPot, Dices } from "lucide-react";
import { useEffect, useState } from "react";

import type { MealSlotResponse } from "../api/types.gen";
import { useSession } from "../auth/session";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { mondayOf } from "../lib/date";
import { i18n } from "../i18n";
import { Button } from "../components/button";
import {
  useClearSlot,
  useGenerateShopping,
  useMarkCooked,
  useCopyWeek,
  useCreateCookTask,
  useCreatePrepTask,
  useSetSlot,
  useSuggestSlot,
  useSuggestWeek,
  useWeek,
  useWeekNutrition,
} from "../mealplan/queries";
import { useRecipes } from "../recipes/queries";

const SLOTS = ["breakfast", "lunch", "dinner", "snack"] as const;
const DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

function shiftWeek(weekStart: string, weeks: number): string {
  const d = new Date(`${weekStart}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + weeks * 7);
  return d.toISOString().slice(0, 10);
}

// Mealplanner week grid (KONZEPT §5.4): the manual core — a recipe or free-text entry per
// day×slot, plus who cooks. Drag&drop + automation come in later slices.
export function MealplanPage() {
  const navigate = useNavigate();
  const { data: session, isLoading: sessionLoading } = useSession();
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()));
  const [targetKcal, setTargetKcal] = useState(""); // per-portion kcal goal (P6-S11)
  const [excludeTags, setExcludeTags] = useState(""); // comma-separated tag exclusions (P6-S13)
  const week = useWeek(weekStart);
  const targetNum = Number.parseInt(targetKcal, 10);
  const nutrition = useWeekNutrition(
    weekStart,
    Number.isFinite(targetNum) && targetNum > 0 ? targetNum : undefined,
  );
  const recipes = useRecipes();
  const setSlot = useSetSlot();
  const clearSlot = useClearSlot();
  const generateShopping = useGenerateShopping();
  const markCooked = useMarkCooked();
  const suggestSlot = useSuggestSlot();
  const suggestWeek = useSuggestWeek();
  const copyWeek = useCopyWeek();
  const cookTask = useCreateCookTask();
  const prepTask = useCreatePrepTask();

  const [editing, setEditing] = useState<string | null>(null); // `${day}-${slot}`
  const [recipeId, setRecipeId] = useState("");
  const [freeText, setFreeText] = useState("");
  const [genMsg, setGenMsg] = useState<string | null>(null);
  const [rollMsg, setRollMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionLoading && session === null) navigate({ to: "/login" });
  }, [sessionLoading, session, navigate]);

  if (sessionLoading || !session) return <LoadingState />;

  const byCell = new Map<string, MealSlotResponse>();
  for (const s of week.data?.slots ?? []) byCell.set(`${s.day_of_week}-${s.slot}`, s);

  const startEdit = (day: number, slot: string) => {
    const cell = byCell.get(`${day}-${slot}`);
    setEditing(`${day}-${slot}`);
    setRecipeId(cell?.recipe_id ?? "");
    setFreeText(cell?.free_text ?? "");
  };

  const save = (day: number, slot: string) => {
    setSlot.mutate(
      {
        weekStart,
        body: {
          day_of_week: day,
          slot: slot as MealSlotResponse["slot"],
          recipe_id: recipeId || null,
          free_text: recipeId ? null : freeText.trim() || null,
        },
      },
      { onSuccess: () => setEditing(null) },
    );
  };

  const clear = (day: number, slot: string) => {
    clearSlot.mutate(
      { weekStart, dayOfWeek: day, slot },
      { onSuccess: () => setEditing(null) },
    );
  };

  // „neu würfeln" (ADR-0052): auto-fill the slot with the least-recently-cooked eligible recipe.
  const roll = (day: number, slot: string) => {
    setRollMsg(null);
    suggestSlot.mutate(
      { weekStart, dayOfWeek: day, slot },
      { onError: () => setRollMsg(i18n._("mealplan.noSuggestion")) },
    );
  };

  // S-02 (ADR-0055): create a „Vorbereiten am Vortag"-task if the recipe needs lead time.
  const prep = (day: number, slot: string) => {
    setRollMsg(null);
    prepTask.mutate(
      { weekStart, dayOfWeek: day, slot },
      {
        onSuccess: (r) => setRollMsg(i18n._("mealplan.prepCreated", { hint: r.hint })),
        onError: () => setRollMsg(i18n._("mealplan.noPrep")),
      },
    );
  };

  return (
    <section aria-labelledby="mealplan-heading" className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 id="mealplan-heading" className="font-display text-2xl">
          <Trans id="mealplan.section" />
        </h1>
        <div className="flex items-center gap-2 text-sm">
          <button
            type="button"
            onClick={() => setWeekStart(shiftWeek(weekStart, -1))}
            className="rounded-md border border-stein/40 px-2 py-1 text-tinte dark:text-kalk hover:border-laurus"
          >
            ‹
          </button>
          <span className="text-stein-text">
            {i18n._("mealplan.weekOf")} {weekStart}
          </span>
          <button
            type="button"
            onClick={() => setWeekStart(shiftWeek(weekStart, 1))}
            className="rounded-md border border-stein/40 px-2 py-1 text-tinte dark:text-kalk hover:border-laurus"
          >
            ›
          </button>
        </div>
      </div>

      {/* S-?? §5.5: fill the shopping list from this week's recipe ingredients. */}
      <div className="flex flex-wrap items-center gap-3">
        <Button
          onClick={() => {
            setGenMsg(null);
            generateShopping.mutate(weekStart, {
              onSuccess: (r) => setGenMsg(i18n._("mealplan.generated", { count: r.added })),
            });
          }}
          disabled={generateShopping.isPending}
        >
          <Trans id="mealplan.toShopping" />
        </Button>
        {/* Fill every empty dinner cell of the week at once (ADR-0052). */}
        <Button
          variant="secondary"
          onClick={() => {
            setRollMsg(null);
            // With a kcal goal entered, fill toward it (P6-S12); otherwise least-recently-cooked.
            const target =
              Number.isFinite(targetNum) && targetNum > 0 ? targetNum : undefined;
            const tags = excludeTags
              .split(",")
              .map((t) => t.trim())
              .filter(Boolean);
            suggestWeek.mutate({ weekStart, slot: "dinner", targetKcal: target, excludeTags: tags });
          }}
          disabled={suggestWeek.isPending}
        >
          {Number.isFinite(targetNum) && targetNum > 0 ? (
            <Trans id="mealplan.rollWeekTarget" />
          ) : (
            <Trans id="mealplan.rollWeek" />
          )}
        </Button>
        {/* Copy the previous week's plan into this week's empty cells (KONZEPT §5.4). */}
        <Button
          variant="secondary"
          onClick={() => {
            setRollMsg(null);
            copyWeek.mutate({ weekStart });
          }}
          disabled={copyWeek.isPending}
        >
          <Trans id="mealplan.copyPrev" />
        </Button>
        {genMsg ? (
          <span className="text-sm text-laurus dark:text-laurus-dark" role="status">
            {genMsg}
          </span>
        ) : null}
        {rollMsg ? (
          <span className="text-sm text-bernstein-text dark:text-bernstein" role="status">
            {rollMsg}
          </span>
        ) : null}
      </div>

      {/* P6-S10/S11 (ADR-0056): week nutrition summary + optional ±10% goal grading. */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
        {nutrition.data && nutrition.data.meals_counted > 0 ? (
          <span className="text-stein-text" role="status">
            {i18n._("mealplan.nutrition", {
              kcal: Math.round(nutrition.data.kcal),
              protein: Math.round(nutrition.data.protein_g),
              fat: Math.round(nutrition.data.fat_g),
              carbs: Math.round(nutrition.data.carbs_g),
              meals: nutrition.data.meals_counted,
            })}
            {nutrition.data.confidence === "estimated"
              ? ` ${i18n._("mealplan.nutritionEstimated")}`
              : ""}
          </span>
        ) : null}
        <label className="flex items-center gap-1 text-stein-text">
          {i18n._("mealplan.targetLabel")}
          <input
            type="number"
            inputMode="numeric"
            min={0}
            value={targetKcal}
            onChange={(e) => setTargetKcal(e.target.value)}
            placeholder="700"
            className="w-20 rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-1 py-0.5 text-tinte dark:text-kalk"
          />
        </label>
        <label className="flex items-center gap-1 text-stein-text">
          {i18n._("mealplan.excludeLabel")}
          <input
            type="text"
            value={excludeTags}
            onChange={(e) => setExcludeTags(e.target.value)}
            placeholder={i18n._("mealplan.excludePlaceholder")}
            className="w-32 rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-1 py-0.5 text-tinte dark:text-kalk"
          />
        </label>
        {nutrition.data?.verdict ? (
          <span
            className={`rounded px-1.5 py-0.5 text-xs ${
              nutrition.data.verdict === "on_target"
                ? "bg-laurus/15 text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark"
                : "bg-bernstein/15 text-bernstein-text dark:text-bernstein"
            }`}
          >
            {i18n._(`mealplan.verdict.${nutrition.data.verdict}`)}
          </span>
        ) : null}
      </div>

      {week.isLoading ? (
        <LoadingState />
      ) : week.isError ? (
        <ErrorState />
      ) : (
        <ul className="space-y-4">
          {DAY_KEYS.map((dayKey, day) => (
            <li key={dayKey} className="rounded-lg border border-stein/30 p-4">
              <h2 className="flex items-center gap-2 font-display text-lg text-tinte dark:text-kalk">
                <Trans id={`mealplan.day.${dayKey}`} />
                {/* S-01 (ADR-0054): the viewer is away this day -> a quiet hint, not a block. */}
                {week.data?.absent_days?.includes(day) ? (
                  <span
                    className="rounded bg-bernstein/15 px-1.5 py-0.5 text-xs font-normal text-bernstein-text dark:text-bernstein"
                    title={i18n._("mealplan.absentHint")}
                  >
                    <Trans id="mealplan.absent" />
                  </span>
                ) : null}
              </h2>
              <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                {SLOTS.map((slot) => {
                  const cellKey = `${day}-${slot}`;
                  const cell = byCell.get(cellKey);
                  const isEditing = editing === cellKey;
                  return (
                    <div key={slot} className="rounded-md bg-stein/5 p-2">
                      <div className="text-xs uppercase tracking-wide text-stein-text">
                        <Trans id={`mealplan.slot.${slot}`} />
                      </div>
                      {isEditing ? (
                        <div className="mt-1 space-y-1">
                          <select
                            value={recipeId}
                            onChange={(e) => setRecipeId(e.target.value)}
                            className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-1 py-1 text-sm text-tinte dark:text-kalk"
                          >
                            <option value="">{i18n._("mealplan.pickRecipe")}</option>
                            {(recipes.data ?? []).map((r) => (
                              <option key={r.id} value={r.id}>
                                {r.title}
                              </option>
                            ))}
                          </select>
                          {!recipeId ? (
                            <input
                              value={freeText}
                              onChange={(e) => setFreeText(e.target.value)}
                              placeholder={i18n._("mealplan.freeText")}
                              className="w-full rounded border border-stein/40 bg-kalk dark:bg-nacht-2 px-1 py-1 text-sm text-tinte dark:text-kalk"
                            />
                          ) : null}
                          <div className="flex gap-2 text-sm">
                            <button
                              type="button"
                              onClick={() => save(day, slot)}
                              disabled={setSlot.isPending}
                              className="text-laurus dark:text-laurus-dark hover:underline"
                            >
                              <Trans id="mealplan.save" />
                            </button>
                            <button
                              type="button"
                              onClick={() => clear(day, slot)}
                              className="text-bernstein-text dark:text-bernstein hover:underline"
                            >
                              <Trans id="mealplan.clear" />
                            </button>
                          </div>
                        </div>
                      ) : (
                        <div className="mt-1 flex items-center justify-between gap-1">
                          <button
                            type="button"
                            onClick={() => startEdit(day, slot)}
                            className="block flex-1 text-left text-sm text-tinte dark:text-kalk hover:text-laurus dark:hover:text-laurus-dark"
                          >
                            {cell?.recipe_title ?? cell?.free_text ?? (
                              <span className="text-stein-text">+</span>
                            )}
                          </button>
                          <button
                            type="button"
                            title={i18n._("mealplan.roll")}
                            aria-label={i18n._("mealplan.roll")}
                            onClick={() => roll(day, slot)}
                            disabled={suggestSlot.isPending}
                            className="rounded-md p-2 -m-1 coarse:p-3 coarse:-m-2 text-stein-text hover:text-laurus dark:hover:text-laurus-dark"
                          >
                            <Dices className="size-4" aria-hidden="true" />
                          </button>
                          {cell?.recipe_title || cell?.free_text ? (
                            <button
                              type="button"
                              title={i18n._("mealplan.cookTask")}
                              aria-label={i18n._("mealplan.cookTask")}
                              onClick={() =>
                                cookTask.mutate({ weekStart, dayOfWeek: day, slot })
                              }
                              disabled={cookTask.isPending}
                              className="rounded-md p-2 -m-1 coarse:p-3 coarse:-m-2 text-stein-text hover:text-laurus dark:hover:text-laurus-dark"
                            >
                              <CookingPot className="size-4" aria-hidden="true" />
                            </button>
                          ) : null}
                          {cell?.recipe_id ? (
                            <button
                              type="button"
                              title={i18n._("mealplan.prepTask")}
                              aria-label={i18n._("mealplan.prepTask")}
                              onClick={() => prep(day, slot)}
                              disabled={prepTask.isPending}
                              className="rounded-md p-2 -m-1 coarse:p-3 coarse:-m-2 text-stein-text hover:text-laurus dark:hover:text-laurus-dark"
                            >
                              <CalendarClock className="size-4" aria-hidden="true" />
                            </button>
                          ) : null}
                          {cell?.recipe_id ? (
                            <button
                              type="button"
                              title={i18n._("mealplan.cooked")}
                              aria-label={i18n._("mealplan.cooked")}
                              onClick={() =>
                                markCooked.mutate({ weekStart, dayOfWeek: day, slot })
                              }
                              disabled={markCooked.isPending}
                              className="rounded-md p-2 -m-1 coarse:p-3 coarse:-m-2 text-laurus hover:text-laurus-dark dark:text-laurus-dark"
                            >
                              <Check className="size-4" aria-hidden="true" />
                            </button>
                          ) : null}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </li>
          ))}
        </ul>
      )}

      {(week.data?.slots.length ?? 0) === 0 && !week.isLoading ? (
        <EmptyState>
          <Trans id="mealplan.empty" />
        </EmptyState>
      ) : null}
    </section>
  );
}
