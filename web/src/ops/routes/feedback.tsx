import { Trans } from "@lingui/react";
import { useState } from "react";

import type { FeedbackDiagnostics } from "../../api/types.gen";
import { DashboardTile } from "../../components/dashboard-tile";
import { i18n } from "../../i18n/ops";
import { useOpsFeedback } from "../queries";

const CATEGORIES = ["bug", "idea", "praise", "other"] as const;

// Operator feedback inbox — reads the ops_feedback view (never the fact table, ADR-0015).
// Feedback is a channel addressed to support, so the message is visible here. Optional
// category filter; newest first (server-ordered).
export function OpsFeedback() {
  const [category, setCategory] = useState<string>("");
  const feedback = useOpsFeedback(category || null);

  return (
    <section aria-labelledby="ops-feedback-heading" className="space-y-4">
      <h1 id="ops-feedback-heading" className="font-display text-2xl">
        <Trans id="ops.feedback.title" />
      </h1>

      <div className="space-y-1">
        <label htmlFor="ops-feedback-category" className="block text-sm font-medium text-tinte dark:text-kalk">
          <Trans id="ops.feedback.category" />
        </label>
        <select
          id="ops-feedback-category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          className="rounded-md border border-stein/40 bg-kalk dark:bg-nacht-2 px-3 py-2 text-tinte dark:text-kalk focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
        >
          <option value="">{i18n._("ops.feedback.all")}</option>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </div>

      <DashboardTile
        title={<Trans id="ops.feedback.inbox" />}
        isLoading={feedback.isLoading}
        isError={feedback.isError}
        isEmpty={(feedback.data?.length ?? 0) === 0}
        emptyText={<Trans id="ops.feedback.empty" />}
      >
        <ul className="space-y-2">
          {feedback.data?.map((f) => {
            // The ops schema carries diagnostics as an opaque object (module-boundary safe);
            // it is the member app's FeedbackDiagnostics shape — narrow for display.
            const diag = (f.diagnostics ?? null) as FeedbackDiagnostics | null;
            return (
            <li key={f.id} className="rounded-md border border-stein/20 p-3">
              <div className="mb-1 flex items-baseline justify-between gap-2 text-xs text-stein-text">
                <span className="rounded bg-stein/15 px-1.5 py-0.5 uppercase">{f.category}</span>
                <span className="font-mono">{f.created_at}</span>
              </div>
              <p className="whitespace-pre-wrap">{f.message}</p>
              {f.route || f.error_ref ? (
                <div className="mt-1 text-xs text-stein-text">
                  {f.route ? <span className="font-mono">{f.route}</span> : null}
                  {f.error_ref ? <span className="ml-2 font-mono">{f.error_ref}</span> : null}
                </div>
              ) : null}
              {diag ? (
                <details className="mt-2 text-xs text-stein-text">
                  <summary className="cursor-pointer">
                    <Trans id="ops.feedback.diagnostics" /> · {diag.app_version}
                  </summary>
                  <ul className="mt-1 space-y-0.5 font-mono">
                    {(diag.entries ?? []).map((d, i) => (
                      <li key={i}>
                        {d.at}
                        {d.route ? ` · ${d.route}` : ""}
                        {d.error_ref ? ` · ${d.error_ref}` : ""}
                        {d.status != null ? ` · ${d.status}` : ""}
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </li>
            );
          })}
        </ul>
      </DashboardTile>
    </section>
  );
}
