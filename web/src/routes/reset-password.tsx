import { Trans } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { ProblemError, useResetPassword } from "../auth/session";
import { AuthShell } from "../components/auth-shell";
import { ResetPasswordForm } from "../components/reset-password-form";

// Slug → i18n: weak/breached password reuse the register copy; an invalid/expired token gets
// its own message.
const ERROR_KEYS: Record<string, string> = {
  weak_password: "auth.error.weak",
  pwned_password: "auth.error.pwned",
  reset_invalid: "auth.reset.invalid",
};

// Set a new password from a reset link. The single-use token rides in the URL query (?token=...).
export function ResetPasswordPage() {
  const reset = useResetPassword();
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const token = new URLSearchParams(window.location.search).get("token") ?? "";

  return (
    <AuthShell
      title={<Trans id="auth.reset.title" />}
      footer={
        <Link to="/login" className="text-laurus hover:underline dark:text-laurus-dark">
          <Trans id="auth.toLogin" />
        </Link>
      }
    >
      <ResetPasswordForm
        pending={reset.isPending}
        error={error}
        done={done}
        onSubmit={(password) => {
          setError(null);
          reset.mutate(
            { token, password },
            {
              onSuccess: () => setDone(true),
              onError: (err) => {
                const slug = err instanceof ProblemError ? err.slug : "error";
                setError(ERROR_KEYS[slug] ?? "state.error");
              },
            },
          );
        }}
      />
    </AuthShell>
  );
}
