import { Trans } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { passkeysSupported } from "../../auth/webauthn";
import { Button } from "../../components/button";
import { ProblemError } from "../../lib/problem";
import { OpsLoginForm, type OpsLoginValues } from "../components/ops-login-form";
import { useOpsLogin, useOpsPasskeyLogin } from "../queries";

// Operator login. Auth is fail-closed: any mismatch (e-mail, password, or TOTP) returns the
// same ``invalid_credentials`` (no operator enumeration), so a single error message suffices.
// Passwordless passkey login is an optional second path (graceful enhancement).
export function OpsLoginPage() {
  const navigate = useNavigate();
  const login = useOpsLogin();
  const passkeyLogin = useOpsPasskeyLogin();
  const [error, setError] = useState<string | null>(null);

  const onSubmit = (values: OpsLoginValues) => {
    setError(null);
    login.mutate(values, {
      onSuccess: () => navigate({ to: "/" }),
      onError: (err) => {
        const slug = err instanceof ProblemError ? err.slug : "error";
        setError(slug === "invalid_credentials" ? "ops.login.error" : "state.error");
      },
    });
  };

  const onPasskey = () => {
    setError(null);
    passkeyLogin.mutate(undefined, {
      onSuccess: () => navigate({ to: "/" }),
      onError: (err) => {
        const slug = err instanceof ProblemError ? err.slug : "error";
        // A user-cancelled ceremony is not an error to surface.
        setError(slug === "passkey_cancelled" ? null : "ops.login.passkeyError");
      },
    });
  };

  return (
    <section aria-labelledby="ops-login-heading" className="mx-auto max-w-sm space-y-6">
      <h1 id="ops-login-heading" className="font-display text-2xl">
        <Trans id="ops.login.title" />
      </h1>
      <OpsLoginForm onSubmit={onSubmit} pending={login.isPending} error={error} />
      {passkeysSupported() ? (
        <div className="space-y-2">
          <p className="text-center text-xs uppercase tracking-wide text-stein-text">
            <Trans id="ops.login.or" />
          </p>
          <Button
            type="button"
            variant="secondary"
            disabled={passkeyLogin.isPending}
            onClick={onPasskey}
            className="w-full"
          >
            <Trans id="ops.login.passkey" />
          </Button>
        </div>
      ) : null}
    </section>
  );
}
