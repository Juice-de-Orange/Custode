import { Trans } from "@lingui/react";

import type { LoginEventResponse } from "../api/types.gen";
import { EmptyState, ErrorState, LoadingState } from "./states";

type LoginActivityProps = {
  events: LoginEventResponse[];
  loading: boolean;
  isError: boolean;
};

// Pure read-only login history (KONFIG §9 Login-Telemetrie): success/failure, country code, time.
// PII-free by construction — the backend never returns IP/e-mail/token. The /security route wires
// the query.
export function LoginActivity({ events, loading, isError }: LoginActivityProps) {
  if (loading) return <LoadingState />;
  if (isError) return <ErrorState />;
  if (events.length === 0) {
    return (
      <EmptyState>
        <Trans id="security.activity.empty" />
      </EmptyState>
    );
  }
  return (
    <ul className="space-y-1 text-sm">
      {events.map((event, index) => (
        <li
          key={`${event.created_at}-${index}`}
          className="flex items-center justify-between gap-3 rounded-md border border-stein/20 px-3 py-1.5"
        >
          <span className={event.success ? "text-laurus dark:text-laurus-dark" : "text-bernstein-text dark:text-bernstein"}>
            <Trans id={event.success ? "security.activity.success" : "security.activity.failure"} />
          </span>
          <span className="text-stein-text">
            {event.country_code ?? <Trans id="security.activity.unknownCountry" />}
          </span>
          <span className="text-stein-text">{new Date(event.created_at).toLocaleString()}</span>
        </li>
      ))}
    </ul>
  );
}
