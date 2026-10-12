import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { ProblemError, useRegister } from "../auth/session";
import { AuthShell } from "../components/auth-shell";
import { RegisterForm, type RegisterValues } from "../components/register-form";
import { useDemo } from "../lib/demo";

const ERROR_KEYS: Record<string, string> = {
  email_taken: "auth.error.email_taken",
  weak_password: "auth.error.weak",
  pwned_password: "auth.error.pwned",
};

export function RegisterPage() {
  const navigate = useNavigate();
  const register = useRegister();
  const [error, setError] = useState<string | null>(null);
  const demo = useDemo();

  const onSubmit = (values: RegisterValues) => {
    setError(null);
    register.mutate(values, {
      onSuccess: () => navigate({ to: "/" }),
      onError: (err) => {
        const slug = err instanceof ProblemError ? err.slug : "error";
        setError(ERROR_KEYS[slug] ?? "state.error");
      },
    });
  };

  return (
    <AuthShell
      title={<Trans id="auth.register.title" />}
      footer={
        <Link to="/login" className="text-laurus hover:underline dark:text-laurus-dark">
          <Trans id="auth.toLogin" />
        </Link>
      }
    >
      {demo ? (
        <p className="text-sm">
          <Trans id="demo.noSignup" />
        </p>
      ) : (
        <RegisterForm onSubmit={onSubmit} pending={register.isPending} error={error} />
      )}
    </AuthShell>
  );
}
