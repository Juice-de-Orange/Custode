import { Trans } from "@lingui/react";
import { useMemo, useState } from "react";

import { OpsAuditList } from "../components/ops-audit-list";
import { useOpsAudit } from "../queries";

// Audit trail (S-OPS-FE-g): read-only view of the append-only audit_log. The write side (operator
// actions + audited sensitive reads) already exists; this closes the loop so operators can inspect
// the trail. Filtering by action is client-side over the loaded page (the log is PII-free).
export function OpsAudit() {
  const audit = useOpsAudit();
  const [action, setAction] = useState("");

  const entries = audit.data ?? [];
  const actions = useMemo(
    () => Array.from(new Set((audit.data ?? []).map((e) => e.action))).sort(),
    [audit.data],
  );
  const shown = action ? entries.filter((e) => e.action === action) : entries;

  return (
    <section aria-labelledby="ops-audit-heading" className="space-y-4">
      <h1 id="ops-audit-heading" className="font-display text-2xl">
        <Trans id="ops.audit.title" />
      </h1>
      <p className="text-sm text-stein-text">
        <Trans id="ops.audit.hint" />
      </p>
      <OpsAuditList
        entries={shown}
        loading={audit.isLoading}
        isError={audit.isError}
        actions={actions}
        action={action}
        onActionChange={setAction}
      />
    </section>
  );
}
