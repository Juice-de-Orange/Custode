import { Trans, useLingui } from "@lingui/react";

import type { DailyMetric, OpsHealth, UsageCounters } from "../../api/types.gen";
import { Sparkline } from "./sparkline";

// Pure presentational views for the KPI dashboard — plain props, no data fetching, so they are
// unit-/axe-testable in isolation. All figures come from aggregate views (no per-household PII).

function Stat({ labelId, value }: { labelId: string; value: number }) {
  return (
    <div className="rounded-md border border-stein/20 p-3">
      <div className="text-2xl font-display tabular-nums">{value}</div>
      <div className="text-sm text-stein-text">
        <Trans id={labelId} />
      </div>
    </div>
  );
}

export function UsageCountersView({ usage }: { usage: UsageCounters }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat labelId="ops.kpi.households" value={usage.households} />
      <Stat labelId="ops.kpi.users" value={usage.users} />
      <Stat labelId="ops.kpi.adults" value={usage.adult_members} />
      <Stat labelId="ops.kpi.children" value={usage.children} />
    </div>
  );
}

// A single signup metric as a sparkline card: hero = the latest day's value, the mini line shows
// the shape, the caption gives the window + total. The exact daily figures stay in the table below.
function TrendCard({ labelId, values }: { labelId: string; values: number[] }) {
  const { i18n } = useLingui();
  const days = values.length;
  const current = values[days - 1] ?? 0;
  const max = days ? Math.max(...values) : 0;
  const total = values.reduce((s, v) => s + v, 0);
  const aria = i18n._("ops.kpi.trend.aria", { label: i18n._(labelId), days, current, max });
  return (
    <div className="rounded-md border border-stein/20 p-3">
      <div className="text-sm text-stein-text">
        <Trans id={labelId} />
      </div>
      <div className="mt-0.5 font-display text-2xl tabular-nums">{current}</div>
      <div className="mt-2">
        <Sparkline values={values} label={aria} />
      </div>
      <div className="mt-1 text-xs text-stein-text tabular-nums">
        <Trans id="ops.kpi.trend.caption" values={{ days, total }} />
      </div>
    </div>
  );
}

export function SignupsView({ daily }: { daily: DailyMetric[] }) {
  // The API returns newest-first (ORDER BY day DESC); the sparklines read oldest → newest.
  const chrono = [...daily].reverse();
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2">
        <TrendCard labelId="ops.kpi.newHouseholds" values={chrono.map((d) => d.new_households)} />
        <TrendCard labelId="ops.kpi.newUsers" values={chrono.map((d) => d.new_users)} />
      </div>
      <table className="w-full text-sm">
        <caption className="sr-only">
          <Trans id="ops.kpi.signups" />
        </caption>
      <thead>
        <tr className="text-left text-stein-text">
          <th scope="col" className="py-1 pr-4 font-medium">
            <Trans id="ops.kpi.day" />
          </th>
          <th scope="col" className="py-1 pr-4 font-medium tabular-nums">
            <Trans id="ops.kpi.newHouseholds" />
          </th>
          <th scope="col" className="py-1 font-medium tabular-nums">
            <Trans id="ops.kpi.newUsers" />
          </th>
        </tr>
      </thead>
      <tbody>
        {daily.map((d) => (
          <tr key={d.day} className="border-t border-stein/15">
            <td className="py-1 pr-4">{d.day}</td>
            <td className="py-1 pr-4 tabular-nums">{d.new_households}</td>
            <td className="py-1 tabular-nums">{d.new_users}</td>
          </tr>
        ))}
      </tbody>
      </table>
    </div>
  );
}

export function HealthView({ health }: { health: OpsHealth }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
      <dt className="text-stein-text">
        <Trans id="ops.health.env" />
      </dt>
      <dd>{health.env}</dd>
      <dt className="text-stein-text">
        <Trans id="ops.health.version" />
      </dt>
      <dd className="tabular-nums">{health.app_version}</dd>
      <dt className="text-stein-text">
        <Trans id="ops.health.gitSha" />
      </dt>
      <dd className="font-mono">{health.git_sha}</dd>
    </dl>
  );
}
