import { Trans } from "@lingui/react";

import { DashboardTile } from "../../components/dashboard-tile";
import { useOpsFlags, useSetFlag } from "../queries";

// Audited global feature-flag management. Every flaggable key renders a toggle reflecting its
// current override (default off when unset); flipping it PUTs the override (record_audit).
export function OpsFlagsPage() {
  const flags = useOpsFlags();
  const setFlag = useSetFlag();

  return (
    <section aria-labelledby="ops-flags-heading" className="space-y-4">
      <h1 id="ops-flags-heading" className="font-display text-2xl">
        <Trans id="ops.flags.title" />
      </h1>

      <DashboardTile
        title={<Trans id="ops.flags.list" />}
        isLoading={flags.isLoading}
        isError={flags.isError}
        isEmpty={(flags.data?.available.length ?? 0) === 0}
        emptyText={<Trans id="ops.flags.empty" />}
      >
        <ul className="space-y-2">
          {flags.data?.available.map((key) => {
            const enabled = flags.data.overrides[key] ?? false;
            return (
              <li
                key={key}
                className="flex items-center justify-between gap-3 rounded-md border border-stein/20 p-3"
              >
                <label htmlFor={`flag-${key}`} className="font-mono text-sm">
                  {key}
                </label>
                <input
                  id={`flag-${key}`}
                  type="checkbox"
                  checked={enabled}
                  disabled={setFlag.isPending}
                  onChange={(e) => setFlag.mutate({ key, enabled: e.target.checked })}
                  className="h-5 w-5 rounded border-stein/40 text-laurus dark:text-laurus-dark focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
                />
              </li>
            );
          })}
        </ul>
      </DashboardTile>
    </section>
  );
}
