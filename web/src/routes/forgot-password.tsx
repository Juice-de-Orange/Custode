import { Trans } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { useState } from "react";

import { useForgotPassword } from "../auth/session";
import { AuthShell } from "../components/auth-shell";
import { ForgotPasswordForm } from "../components/forgot-password-form";
import { useDemo } from "../lib/demo";

// Request a password-reset link. The form always shows the same confirmation after submit,
// whether or not the address exists (no enumeration); the request is best-effort.
export function ForgotPasswordPage() {
  const forgot = useForgotPassword();
  const [submitted, setSubmitted] = useState(false);
  const demo = useDemo();

  return (
    <AuthShell
      title={<Trans id="auth.forgot.title" />}
      footer={
        <Link to="/login" className="text-laurus hover:underline dark:text-laurus-dark">
          <Trans id="auth.toLogin" />
        </Link>
      }
    >
      {demo ? (
        <p className="text-sm">
          <Trans id="demo.noMail" />
        </p>
      ) : (
        <ForgotPasswordForm
          pending={forgot.isPending}
          submitted={submitted}
          onSubmit={(email) => forgot.mutate(email, { onSettled: () => setSubmitted(true) })}
        />
      )}
    </AuthShell>
  );
}
