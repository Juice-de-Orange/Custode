import { Trans, useLingui } from "@lingui/react";

import { STARTERS, type StarterRecipe, localizeStarter } from "../lib/starters";
import { Button } from "./button";

// Onboarding: add a curated starter recipe to the household with one tap (P2-S7). Localized to the
// active UI language. The caller wires `onAdd` to useCreateRecipe.
export function StarterPicker({
  onAdd,
  pending,
}: {
  onAdd: (starter: StarterRecipe) => void;
  pending: boolean;
}) {
  const { i18n } = useLingui();
  const starters = STARTERS.map((starter) => localizeStarter(starter, i18n.locale));

  return (
    <div className="space-y-3">
      <p className="text-sm text-stein-text">
        <Trans id="starter.hint" />
      </p>
      <ul className="grid gap-3 sm:grid-cols-2">
        {starters.map((starter) => (
          <li
            key={starter.id}
            className="flex items-center justify-between gap-3 rounded-lg border border-stein/30 p-3"
          >
            <div className="min-w-0">
              <span className="block truncate text-tinte dark:text-kalk">{starter.title}</span>
              {starter.tags.length > 0 ? (
                <span className="text-xs text-stein-text">{starter.tags.join(" · ")}</span>
              ) : null}
            </div>
            <Button
              type="button"
              onClick={() => onAdd(starter)}
              disabled={pending}
              className="shrink-0 px-3 py-1 text-sm"
            >
              <Trans id="starter.add" />
            </Button>
          </li>
        ))}
      </ul>
    </div>
  );
}
