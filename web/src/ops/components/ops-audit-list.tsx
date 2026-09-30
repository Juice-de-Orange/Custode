import { Trans, useLingui } from "@lingui/react";

import type { AuditLogEntry } from "../../api/types.gen";
import { DashboardTile } from "../../components/dashboard-tile";

type OpsAuditListProps = {
  entries: AuditLogEntry[];
  loading: boolean;
  isError: boolean;
  actions: string[]; // distinct action names for the filter, derived from the loaded data
  action: string; // selected action filter, "" = all
  onActionChange: (action: string) => void;
};

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString();
}

// Compact, PII-free rendering of the structured detail_json (query lengths, counts, keys — never
// content). Values are stringified defensively.
function formatDetail(detail: Record<string, unknown>): string {
  return Object.entries(detail)
    .map(([key, value]) => `${key}: ${String(value)}`)
    .join(" · ");
}

// Pure audit-trail list + action filter. The audit_log is append-only and PII-free by construction,
// so this is read-only: action strings are stable technical identifiers, shown verbatim (not
// translated). The route derives the filter options and owns the query.
export function OpsAuditList({
  entries,
  loading,
  isError,
  actions,
  action,
  onActionChange,
}: OpsAuditListProps) {
  const { i18n } = useLingui();
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <label htmlFor="ops-audit-action" className="text-sm text-stein-text">
          <Trans id="ops.audit.action" />
        </label>
        <select
          id="ops-audit-action"
          value={action}
          onChange={(event) => onActionChange(event.target.value)}
          className="rounded-md border border-stein/40 bg-transparent px-2 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-laurus/40"
        >
          <option value="">{i18n._("ops.audit.all")}</option>
          {actions.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </div>

      <DashboardTile
        title={<Trans id="ops.audit.list" />}
        isLoading={loading}
        isError={isError}
        isEmpty={entries.length === 0}
        emptyText={<Trans id="ops.audit.empty" />}
      >
        <ul className="space-y-2">
          {entries.map((entry) => {
            const detail = formatDetail(entry.detail);
            return (
              <li
                key={entry.id}
                className="rounded-md border border-stein/20 p-3 text-sm"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-mono text-xs">{entry.action}</span>
                  <span className="text-xs text-stein-text">{formatWhen(entry.occurred_at)}</span>
                </div>
                <div className="mt-1 text-xs text-stein-text">
                  {entry.actor_type}
                  {entry.target_type ? ` → ${entry.target_type}` : ""}
                  {detail ? ` · ${detail}` : ""}
                </div>
              </li>
            );
          })}
        </ul>
      </DashboardTile>
    </div>
  );
}
