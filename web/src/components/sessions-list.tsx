import { Trans, useLingui } from "@lingui/react";

import type { SessionView } from "../api/types.gen";
import { Button } from "./button";
import { EmptyState, ErrorState, LoadingState } from "./states";

type SessionsListProps = {
  sessions: SessionView[];
  loading: boolean;
  isError: boolean;
  revokePendingId: string | null;
  onRevoke: (familyId: string) => void;
};

function deviceName(session: SessionView): string {
  return session.device_label || session.user_agent || "";
}

// Pure device/session list with remote logout (KONFIG §8). The current session is badged and
// confirms with a stronger warning (revoking it logs this device out). The /security route wires
// the query + revoke mutation; window.confirm keeps the destructive action accessible.
export function SessionsList({
  sessions,
  loading,
  isError,
  revokePendingId,
  onRevoke,
}: SessionsListProps) {
  const { i18n } = useLingui();
  if (loading) return <LoadingState />;
  if (isError) return <ErrorState />;
  if (sessions.length === 0) {
    return (
      <EmptyState>
        <Trans id="security.sessions.empty" />
      </EmptyState>
    );
  }
  return (
    <ul className="space-y-2">
      {sessions.map((session) => (
        <li
          key={session.family_id}
          className="flex items-center justify-between gap-3 rounded-md border border-stein/30 px-3 py-2"
        >
          <div className="min-w-0">
            <p className="truncate font-medium">
              {deviceName(session) || <Trans id="security.sessions.unknownDevice" />}
              {session.current ? (
                <span className="ml-2 rounded bg-laurus/15 px-1.5 py-0.5 text-xs text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark">
                  <Trans id="security.sessions.current" />
                </span>
              ) : null}
            </p>
            <p className="text-sm text-stein-text">
              <Trans id="security.sessions.lastUsed" />{" "}
              {new Date(session.last_used_at).toLocaleString()}
            </p>
          </div>
          <Button
            type="button"
            disabled={revokePendingId === session.family_id}
            onClick={() => {
              const key = session.current
                ? "security.sessions.confirmRevokeCurrent"
                : "security.sessions.confirmRevoke";
              if (window.confirm(i18n._(key))) onRevoke(session.family_id);
            }}
            className="shrink-0 bg-stein/20 text-tinte dark:text-kalk hover:bg-stein/30"
          >
            <Trans id="security.sessions.revoke" />
          </Button>
        </li>
      ))}
    </ul>
  );
}
