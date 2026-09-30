import { Trans } from "@lingui/react";
import { useState } from "react";

import { passkeysSupported } from "../../auth/webauthn";
import { PasskeyManager } from "../../components/passkey-manager";
import { ProblemError } from "../../lib/problem";
import { useDeleteOpsPasskey, useOpsPasskeys, useRegisterOpsPasskey } from "../queries";

// The operator's own passkey enrolment. Reuses the pure PasskeyManager (the ops summary type is
// structurally identical to the member PasskeyResponse) and the generic ``security.passkeys.*``
// strings; only the heading/hint and add-error are ops-specific.
export function OpsPasskeysPage() {
  const passkeys = useOpsPasskeys();
  const register = useRegisterOpsPasskey();
  const remove = useDeleteOpsPasskey();
  const [error, setError] = useState<string | null>(null);

  const onAdd = (name: string) => {
    setError(null);
    register.mutate(name, {
      onError: (err) => {
        const slug = err instanceof ProblemError ? err.slug : "error";
        // A user-cancelled ceremony is not an error to surface.
        setError(slug === "passkey_cancelled" ? null : "ops.passkeys.error");
      },
    });
  };

  // Deleting a passkey revokes a login credential — a silent failure would wrongly imply success,
  // so route delete errors into the same alert the add path uses (mirrors the member /security view).
  const onDelete = (id: string) => {
    setError(null);
    remove.mutate(id, { onError: () => setError("ops.passkeys.deleteError") });
  };

  return (
    <section aria-labelledby="ops-passkeys-heading" className="mx-auto max-w-lg space-y-4">
      <h1 id="ops-passkeys-heading" className="font-display text-2xl">
        <Trans id="ops.passkeys.title" />
      </h1>
      <p className="text-sm text-stein-text">
        <Trans id="ops.passkeys.hint" />
      </p>
      <PasskeyManager
        passkeys={passkeys.data ?? []}
        loading={passkeys.isLoading}
        isError={passkeys.isError}
        supported={passkeysSupported()}
        error={error}
        addPending={register.isPending}
        deletePendingId={remove.isPending ? (remove.variables ?? null) : null}
        onAdd={onAdd}
        onDelete={onDelete}
      />
    </section>
  );
}
