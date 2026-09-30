import { Trans } from "@lingui/react";

import type { NutritionOut } from "../api/types.gen";

const MACROS: { key: "protein_g" | "fat_g" | "carbs_g" | "sugar_g" | "fiber_g"; label: string }[] = [
  { key: "protein_g", label: "nutrition.protein" },
  { key: "fat_g", label: "nutrition.fat" },
  { key: "carbs_g", label: "nutrition.carbs" },
  { key: "sugar_g", label: "nutrition.sugar" },
  { key: "fiber_g", label: "nutrition.fiber" },
];

// Per-portion nutrition summary (S5b). Pure — the recipe detail passes the computed values; an
// "estimated" badge flags incomplete coverage (unmapped ingredients).
export function NutritionPanel({ data }: { data: NutritionOut }) {
  return (
    <div className="rounded-lg border border-stein/30 p-4">
      <div className="flex items-baseline justify-between gap-4">
        <span className="font-display text-xl text-tinte dark:text-kalk">
          {Math.round(data.kcal)} <span className="text-sm font-normal text-stein-text">kcal</span>
        </span>
        <span className="text-xs text-stein-text">
          <Trans id="nutrition.perPortion" />
          {data.confidence === "estimated" ? (
            <span className="ml-2 text-bernstein-text dark:text-bernstein">
              <Trans id="nutrition.estimated" />
            </span>
          ) : null}
        </span>
      </div>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1 text-sm">
        {MACROS.map((macro) => (
          <div key={macro.key} className="flex justify-between">
            <dt className="text-stein-text">
              <Trans id={macro.label} />
            </dt>
            <dd className="text-tinte dark:text-kalk">{data[macro.key].toFixed(1)} g</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
