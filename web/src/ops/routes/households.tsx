import { Trans } from "@lingui/react";
import { useState } from "react";

import { Field } from "../../components/field";
import { DashboardTile } from "../../components/dashboard-tile";
import { useSearchHouseholds } from "../queries";

// Support search — household **metadata only** (name, age, member counts), never content
// (recipes/tasks/messages), ADR-0015. Empty query lists the most recent households.
export function OpsHouseholds() {
  const [query, setQuery] = useState("");
  const [submitted, setSubmitted] = useState("");
  const results = useSearchHouseholds(submitted);

  return (
    <section aria-labelledby="ops-households-heading" className="space-y-4">
      <h1 id="ops-households-heading" className="font-display text-2xl">
        <Trans id="ops.households.title" />
      </h1>

      <form
        className="flex items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(query.trim());
        }}
      >
        <div className="flex-1">
          <Field
            id="ops-household-search"
            label={<Trans id="ops.households.search" />}
            value={query}
            maxLength={200}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <button
          type="submit"
          className="rounded-md bg-laurus px-4 py-2 text-kalk hover:bg-laurus/90 focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
        >
          <Trans id="ops.households.searchButton" />
        </button>
      </form>

      <DashboardTile
        title={<Trans id="ops.households.results" />}
        isLoading={results.isLoading}
        isError={results.isError}
        isEmpty={(results.data?.length ?? 0) === 0}
        emptyText={<Trans id="ops.households.empty" />}
      >
        <ul className="space-y-2">
          {results.data?.map((h) => (
            <li key={h.id} className="rounded-md border border-stein/20 p-3">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{h.name}</span>
                <span className="font-mono text-xs text-stein-text">{h.id}</span>
              </div>
              <div className="text-sm text-stein-text">
                <Trans id="ops.households.members" />: {h.member_count} · <Trans id="ops.households.admins" />:{" "}
                {h.admin_count}
              </div>
            </li>
          ))}
        </ul>
      </DashboardTile>
    </section>
  );
}
