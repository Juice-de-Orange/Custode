import { Trans } from "@lingui/react";

import { DashboardTile } from "../../components/dashboard-tile";
import { useOpsOperators, useOpsSession, useSetOperatorActive } from "../queries";

// Operator management (S-OPS-FE-e): list every operator + activate/deactivate (audited server-side,
// ops_actions). Provisioning stays CLI/seed (ADR-0015) — this manages activation, not credentials.
// The current operator's own deactivate is disabled (mirrors the server 409 self-guard).
export function OpsOperators() {
  const operators = useOpsOperators();
  const setActive = useSetOperatorActive();
  const meId = useOpsSession().data?.id;

  return (
    <section aria-labelledby="ops-operators-heading" className="space-y-4">
      <h1 id="ops-operators-heading" className="font-display text-2xl">
        <Trans id="ops.operators.title" />
      </h1>
      <p className="text-sm text-stein-text">
        <Trans id="ops.operators.hint" />
      </p>
      {setActive.isError ? (
        <p role="alert" className="text-sm text-rost dark:text-bernstein">
          <Trans id="ops.operators.actionError" />
        </p>
      ) : null}

      <DashboardTile
        title={<Trans id="ops.operators.list" />}
        isLoading={operators.isLoading}
        isError={operators.isError}
        isEmpty={(operators.data?.length ?? 0) === 0}
        emptyText={<Trans id="ops.operators.empty" />}
      >
        <ul className="space-y-2">
          {operators.data?.map((op) => {
            const isSelf = op.id === meId;
            return (
              <li
                key={op.id}
                className="flex items-center justify-between gap-3 rounded-md border border-stein/20 p-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm">
                    {op.email}
                    {isSelf ? (
                      <span className="ml-1 text-xs text-stein-text">
                        (<Trans id="ops.operators.you" />)
                      </span>
                    ) : null}
                  </div>
                  <div className="text-xs text-stein-text">
                    <Trans id={op.is_active ? "ops.operators.active" : "ops.operators.inactive"} />
                    {" · "}
                    <Trans id={op.totp_enabled ? "ops.operators.totpOn" : "ops.operators.totpOff"} />
                  </div>
                </div>
                <button
                  type="button"
                  disabled={isSelf || setActive.isPending}
                  onClick={() => setActive.mutate({ id: op.id, active: !op.is_active })}
                  className="shrink-0 rounded-md border border-stein/40 px-3 py-1 text-sm hover:bg-stein/10 disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:hover:bg-kalk/10 dark:focus:ring-laurus-dark/40"
                >
                  <Trans id={op.is_active ? "ops.operators.deactivate" : "ops.operators.reactivate"} />
                </button>
              </li>
            );
          })}
        </ul>
      </DashboardTile>
    </section>
  );
}
