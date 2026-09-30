import { Trans } from "@lingui/react";

import { DashboardTile } from "../../components/dashboard-tile";
import { HealthView, SignupsView, UsageCountersView } from "../components/kpi-views";
import { useOpsHealth, useOpsKpis } from "../queries";

// Authenticated landing for the console: global counters, the signup curve and build/health
// info — all from aggregate views / build metadata only (ADR-0015/0071, no per-household PII).
// Banners/flags, support search and the feedback inbox arrive in S-OPS-FE-c..d.
export function OpsDashboard() {
  const kpis = useOpsKpis();
  const health = useOpsHealth();

  return (
    <section aria-labelledby="ops-dashboard-heading" className="space-y-4">
      <h1 id="ops-dashboard-heading" className="font-display text-2xl">
        <Trans id="ops.dashboard.title" />
      </h1>

      <DashboardTile
        title={<Trans id="ops.kpi.usage" />}
        isLoading={kpis.isLoading}
        isError={kpis.isError}
        isEmpty={false}
      >
        {kpis.data ? <UsageCountersView usage={kpis.data.usage} /> : null}
      </DashboardTile>

      <DashboardTile
        title={<Trans id="ops.kpi.signups" />}
        isLoading={kpis.isLoading}
        isError={kpis.isError}
        isEmpty={(kpis.data?.daily.length ?? 0) === 0}
        emptyText={<Trans id="ops.kpi.signups.empty" />}
      >
        {kpis.data ? <SignupsView daily={kpis.data.daily} /> : null}
      </DashboardTile>

      <DashboardTile
        title={<Trans id="ops.health.title" />}
        isLoading={health.isLoading}
        isError={health.isError}
        isEmpty={false}
      >
        {health.data ? <HealthView health={health.data} /> : null}
      </DashboardTile>
    </section>
  );
}
