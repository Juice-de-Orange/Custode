import { Trans, useLingui } from "@lingui/react";
import { type FormEvent, useState } from "react";

import type { PasskeyResponse } from "../api/types.gen";
import { Button } from "./button";
import { EmptyState, ErrorState, LoadingState } from "./states";
import { Field } from "./field";

type PasskeyManagerProps = {
  passkeys: PasskeyResponse[];
  loading: boolean;
  isError: boolean;
  supported: boolean; // window.PublicKeyCredential present
  error: string | null; // i18n key for add/delete failures
  addPending: boolean;
  deletePendingId: string | null;
  onAdd: (name: string) => void;
  onDelete: (id: string) => void;
};

function formatDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleDateString() : "";
}

// Pure passkey list + add/delete. The list shows the Trio (loading/empty/error); adding is gated
// on browser support (graceful enhancement — password/TOTP stay the base path). The /security
// route wires the ceremony (session.ts useRegisterPasskey) and slug→i18n error mapping.
export function PasskeyManager({
  passkeys,
  loading,
  isError,
  supported,
  error,
  addPending,
  deletePendingId,
  onAdd,
  onDelete,
}: PasskeyManagerProps) {
  const { i18n } = useLingui();
  const [name, setName] = useState("");

  const handleAdd = (event: FormEvent) => {
    event.preventDefault();
    onAdd(name);
    setName("");
  };

  return (
    <div className="space-y-4">
      {loading ? (
        <LoadingState />
      ) : isError ? (
        <ErrorState />
      ) : passkeys.length === 0 ? (
        <EmptyState>
          <Trans id="security.passkeys.empty" />
        </EmptyState>
      ) : (
        <ul className="space-y-2">
          {passkeys.map((passkey) => (
            <li
              key={passkey.id}
              className="flex items-center justify-between rounded-md border border-stein/30 px-3 py-2"
            >
              <div>
                <p className="font-medium">{passkey.name}</p>
                <p className="text-sm text-stein-text">
                  <Trans id="security.passkeys.created" /> {formatDate(passkey.created_at)}
                </p>
              </div>
              <Button
                type="button"
                disabled={deletePendingId === passkey.id}
                onClick={() => {
                  if (window.confirm(i18n._("security.passkeys.confirmDelete"))) {
                    onDelete(passkey.id);
                  }
                }}
                className="bg-stein/20 text-tinte dark:text-kalk hover:bg-stein/30"
              >
                <Trans id="security.passkeys.delete" />
              </Button>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={handleAdd} className="space-y-3" noValidate>
        <Field
          id="passkey-name"
          required
          disabled={!supported}
          value={name}
          onChange={(event) => setName(event.target.value)}
          label={<Trans id="security.passkeys.nameLabel" />}
        />
        {!supported ? (
          <p className="text-sm text-stein-text">
            <Trans id="security.passkeys.unsupported" />
          </p>
        ) : null}
        {error ? (
          <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
            <Trans id={error} />
          </p>
        ) : null}
        <Button type="submit" disabled={!supported || addPending}>
          <Trans id="security.passkeys.add" />
        </Button>
      </form>
    </div>
  );
}
