import { Trans } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import { useId, type ReactNode } from "react";

import { EmptyState, ErrorState, LoadingState } from "./states";

type DashboardTileProps = {
  title: ReactNode;
  // Optional deep-link into the owning module, rendered as a quiet „alle ansehen" affordance.
  to?: string;
  isLoading: boolean;
  isError: boolean;
  isEmpty: boolean;
  emptyText?: ReactNode;
  children: ReactNode;
};

// One „Heute" dashboard tile. Owns the DoD trio (Loading/Empty/Error) so every tile gets it for
// free, and is a labelled landmark (`section` + `aria-labelledby`) for screen readers + axe.
export function DashboardTile({
  title,
  to,
  isLoading,
  isError,
  isEmpty,
  emptyText,
  children,
}: DashboardTileProps) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      className="rounded-card border border-stein/15 bg-papier p-5 shadow-soft transition-shadow hover:shadow-elev dark:border-stein/15 dark:bg-nacht-2"
    >
      <div className="mb-3 flex items-baseline justify-between gap-2">
        <h2 id={headingId} className="font-display text-lg font-semibold tracking-tight">
          {title}
        </h2>
        {to ? (
          <Link
            to={to}
            className="group inline-flex items-center gap-1 text-sm text-laurus hover:underline dark:text-laurus-dark"
          >
            <Trans id="today.viewAll" />
            <ArrowRight
              className="size-3.5 transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none"
              aria-hidden="true"
            />
          </Link>
        ) : null}
      </div>
      {isLoading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState />
      ) : isEmpty ? (
        <EmptyState>{emptyText}</EmptyState>
      ) : (
        children
      )}
    </section>
  );
}
