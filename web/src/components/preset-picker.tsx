import { Trans, useLingui } from "@lingui/react";

import { PRESETS, localizePreset } from "../lib/presets";
import { useApplyPreset, useRooms, useTaskTemplates } from "../tasks/queries";
import { Button } from "./button";
import { ErrorState } from "./states";

// Onboarding quick-start (P8-S2): offered to a fresh, empty household's admin. Picking a preset seeds
// rooms + typical task templates in one step. Self-hides once the household has any rooms or templates,
// so it only ever appears on first run; everything stays editable on /rooms and /tasks afterwards.
export function OnboardingPresets() {
  const { i18n } = useLingui();
  const rooms = useRooms();
  const templates = useTaskTemplates();
  const apply = useApplyPreset();

  if (rooms.isLoading || templates.isLoading) return null;
  if ((rooms.data?.length ?? 0) > 0 || (templates.data?.length ?? 0) > 0) return null;

  const presets = PRESETS.map((preset) => localizePreset(preset, i18n.locale));

  return (
    <section
      aria-labelledby="onboarding-heading"
      className="space-y-3 rounded-card border border-laurus/30 bg-laurus/5 p-5 shadow-soft dark:border-laurus-dark/30 dark:bg-laurus-dark/10"
    >
      <h3 id="onboarding-heading" className="font-display text-lg font-semibold tracking-tight">
        <Trans id="onboarding.title" />
      </h3>
      <p className="text-sm text-stein-text">
        <Trans id="onboarding.intro" />
      </p>
      {apply.isError ? <ErrorState /> : null}
      <ul className="grid gap-3 sm:grid-cols-3">
        {presets.map((preset) => (
          <li
            key={preset.id}
            className="flex flex-col gap-2 rounded-md border border-stein/25 bg-papier p-3 dark:border-stein/20 dark:bg-nacht-2"
          >
            <h4 className="font-medium text-tinte dark:text-kalk">
              <Trans id={`preset.${preset.id}.title`} />
            </h4>
            <p className="grow text-sm text-stein-text">
              <Trans id={`preset.${preset.id}.desc`} />
            </p>
            <p className="text-xs text-stein-text">
              {i18n._("onboarding.summary", {
                rooms: preset.rooms.length,
                tasks: preset.templates.length,
              })}
            </p>
            <Button
              type="button"
              size="sm"
              onClick={() => apply.mutate(preset)}
              disabled={apply.isPending}
            >
              {apply.isPending ? <Trans id="onboarding.seeding" /> : <Trans id="onboarding.apply" />}
            </Button>
          </li>
        ))}
      </ul>
    </section>
  );
}
