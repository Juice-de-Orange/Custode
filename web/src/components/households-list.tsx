import { Trans } from "@lingui/react";

import type { HouseholdSummary } from "../api/types.gen";
import { Button } from "./button";

type Props = {
  households: HouseholdSummary[];
  activeId: string | null;
  onSwitch: (id: string) => void;
  pendingId: string | null;
};

export function HouseholdsList({ households, activeId, onSwitch, pendingId }: Props) {
  if (households.length === 0) {
    return (
      <p className="text-sm text-stein-text">
        <Trans id="household.none" />
      </p>
    );
  }
  return (
    <ul className="space-y-2">
      {households.map((h) => (
        <li
          key={h.household_id}
          className="flex items-center justify-between gap-3 rounded-md border border-stein/30 px-3 py-2"
        >
          <span>
            <span className="font-medium">{h.name}</span>
            <span className="ml-2 text-sm text-stein-text">{h.role}</span>
          </span>
          {h.household_id === activeId ? (
            <span className="text-sm text-laurus dark:text-laurus-dark">
              <Trans id="household.active" />
            </span>
          ) : (
            <Button
              type="button"
              disabled={pendingId === h.household_id}
              onClick={() => onSwitch(h.household_id)}
              className="text-sm"
            >
              <Trans id="household.switch" />
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
}
