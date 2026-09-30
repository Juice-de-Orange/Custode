// Wearable connection management (P9-S8). Lives on /profile, not on a household page — the data
// is member-private (Art. 9, N-2), so it belongs where a person manages their own things.
//
// Self-contained (own hooks, no props) like DigestToggle; ConsentPicker/ConnectionCard are
// presentational and hook-free so the a11y gate and component tests can render them without a
// QueryClient. Nothing here ever shows a score or a value: the UI states WHETHER a connection
// exists and WHICH types are consented, never what was measured.

import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import type { ConnectionResponse } from "../api/types.gen";
import { Button } from "../components/button";
import { ErrorState, LoadingState } from "../components/states";
import { i18n } from "../i18n";
import { callbackMessage, connectionStatusId, wearableProblemMessage } from "./errors";
import {
  CONSENT_TYPES,
  type ConsentType,
  useAuthorize,
  useConnections,
  useDisconnect,
  useUpdateConsents,
} from "./queries";

const TYPE_LABELS: Record<ConsentType, string> = {
  wearable_sleep: "wearables.type.sleep",
  wearable_readiness: "wearables.type.readiness",
  wearable_activity: "wearables.type.activity",
  wearable_heartrate: "wearables.type.heartrate",
};

// --- presentational ---------------------------------------------------------

export function ConsentPicker({
  selected,
  onToggle,
  idPrefix,
  disabled = false,
}: {
  selected: Set<string>;
  onToggle: (type: ConsentType) => void;
  idPrefix: string;
  disabled?: boolean;
}) {
  return (
    <fieldset className="space-y-2">
      <legend className="text-sm text-stein-text">
        <Trans id="wearables.consentLegend" />
      </legend>
      {CONSENT_TYPES.map((type) => (
        <label key={type} htmlFor={`${idPrefix}-${type}`} className="flex items-center gap-2">
          <input
            id={`${idPrefix}-${type}`}
            type="checkbox"
            checked={selected.has(type)}
            disabled={disabled}
            onChange={() => onToggle(type)}
            className="size-4"
          />
          <span className="text-sm">
            <Trans id={TYPE_LABELS[type]} />
          </span>
        </label>
      ))}
    </fieldset>
  );
}

export function ConnectionStatus({ connection }: { connection: ConnectionResponse }) {
  const id = connectionStatusId(connection.status, connection.last_error);
  const urgent = connection.status === "needs_reauth";
  return (
    <p className={`text-sm ${urgent ? "text-rost" : "text-stein-text"}`}>
      <Trans id={id} />
    </p>
  );
}

// --- container --------------------------------------------------------------

/** ``callbackCode`` is the ``?connected=``/``?error=`` the backend redirect carries. */
export function WearablesSection({
  connected,
  callbackError,
}: {
  connected?: string;
  callbackError?: string;
}) {
  const connections = useConnections();
  const authorize = useAuthorize();
  const updateConsents = useUpdateConsents();
  const disconnect = useDisconnect();
  const [selected, setSelected] = useState<Set<string>>(new Set(["wearable_sleep"]));
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggle(type: ConsentType) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(type)) next.delete(type);
      else next.add(type);
      return next;
    });
  }

  if (connections.isLoading) return <LoadingState />;
  if (connections.isError) return <ErrorState />;

  const connection = connections.data?.[0] ?? null;

  function handleConnect(event: FormEvent) {
    event.preventDefault();
    setError(null);
    authorize.mutate([...selected], {
      // Full navigation, not a popup: the provider redirects back to a server route which then
      // sends the browser home. A popup would lose that chain.
      onSuccess: (url) => window.location.assign(url),
      onError: (err) => setError(wearableProblemMessage(err).id),
    });
  }

  return (
    <section aria-labelledby="wearables-heading" className="space-y-3">
      <h2 id="wearables-heading" className="font-display text-lg">
        <Trans id="wearables.title" />
      </h2>
      <p className="text-sm text-stein-text">
        <Trans id="wearables.intro" />
      </p>

      {connected && !connection && (
        <p role="status" className="text-sm text-stein-text">
          <Trans id="wearables.cb.connected" />
        </p>
      )}
      {callbackError && (
        <p role="alert" className="text-sm text-rost">
          <Trans id={callbackMessage(callbackError).id} />
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-rost">
          <Trans id={error} />
        </p>
      )}

      {connection ? (
        <div className="space-y-3 rounded-lg border border-stein/30 p-4">
          <p className="font-medium">
            <Trans id="wearables.provider.oura" />
          </p>
          <ConnectionStatus connection={connection} />
          <ConsentPicker
            idPrefix="wearables-edit"
            selected={new Set(connection.consent_types)}
            disabled={updateConsents.isPending}
            onToggle={(type) => {
              const next = new Set(connection.consent_types);
              if (next.has(type)) next.delete(type);
              else next.add(type);
              setError(null);
              updateConsents.mutate(
                { id: connection.id, consentTypes: [...next] },
                { onError: (err) => setError(wearableProblemMessage(err).id) },
              );
            }}
          />
          <p className="text-xs text-stein-text">
            <Trans id="wearables.consentHint" />
          </p>

          {confirmingDelete ? (
            <div className="space-y-2">
              <p className="text-sm">
                <Trans id="wearables.disconnectConfirm" />
              </p>
              <div className="flex gap-2">
                <Button
                  variant="danger"
                  disabled={disconnect.isPending}
                  onClick={() => {
                    setError(null);
                    disconnect.mutate(connection.id, {
                      onSuccess: () => setConfirmingDelete(false),
                      onError: (err) => setError(wearableProblemMessage(err).id),
                    });
                  }}
                >
                  <Trans id="wearables.disconnectDo" />
                </Button>
                <Button variant="ghost" onClick={() => setConfirmingDelete(false)}>
                  <Trans id="wearables.cancel" />
                </Button>
              </div>
            </div>
          ) : (
            <Button variant="ghost" onClick={() => setConfirmingDelete(true)}>
              <Trans id="wearables.disconnect" />
            </Button>
          )}
        </div>
      ) : (
        <form onSubmit={handleConnect} className="space-y-3 rounded-lg border border-stein/30 p-4">
          <ConsentPicker
            idPrefix="wearables-new"
            selected={selected}
            onToggle={toggle}
            disabled={authorize.isPending}
          />
          <p className="text-xs text-stein-text">
            <Trans id="wearables.connectHint" />
          </p>
          <Button type="submit" disabled={authorize.isPending || selected.size === 0}>
            {authorize.isPending
              ? i18n._("wearables.connecting")
              : i18n._("wearables.connect")}
          </Button>
        </form>
      )}
    </section>
  );
}
