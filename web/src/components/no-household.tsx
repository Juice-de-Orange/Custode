import { Trans } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { Home } from "lucide-react";

// Shown instead of a module screen when the session has no active household — a fresh
// account before its first household, or a multi-household member before picking one.
// Without this every household-scoped query on the route 403s into generic error boxes
// (P8 Prod-QA finding); this state says why and offers the next sensible step (P7).
export function NoHouseholdState() {
  return (
    <section
      aria-labelledby="no-household-heading"
      className="flex flex-col items-center gap-3 rounded-card border border-stein/25 bg-papier/50 px-6 py-10 text-center dark:bg-nacht-2/50"
    >
      <span className="text-stein-text/70" aria-hidden="true">
        <Home className="size-7" strokeWidth={1.5} />
      </span>
      <h1 id="no-household-heading" className="font-display text-xl">
        <Trans id="shell.noHousehold.title" />
      </h1>
      <p className="max-w-md text-sm text-stein-text">
        <Trans id="shell.noHousehold.hint" />
      </p>
      <Link
        to="/"
        className="mt-1 rounded-pill bg-laurus px-4 py-2 text-sm font-medium text-kalk hover:bg-laurus/90 dark:bg-laurus-dark dark:text-nacht"
      >
        <Trans id="shell.noHousehold.cta" />
      </Link>
    </section>
  );
}
