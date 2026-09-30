import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { ProblemError, useChildLogin } from "../auth/session";
import { AuthShell } from "../components/auth-shell";
import { ChildLoginForm } from "../components/child-login-form";

const ERROR_KEYS: Record<string, string> = {
  invalid_pin: "child.error.pin",
  too_many_attempts: "child.error.locked",
};

// Child sign-in (username + PIN). The household is carried in the URL (?household=...) — a parent
// shares this link / opens it on the family device; kids never type a UUID.
export function ChildLoginPage() {
  const navigate = useNavigate();
  const childLogin = useChildLogin();
  const [error, setError] = useState<string | null>(null);
  const household = new URLSearchParams(window.location.search).get("household") ?? "";

  return (
    <AuthShell
      title={<Trans id="child.login.title" />}
      footer={
        <Link to="/login" className="text-laurus hover:underline dark:text-laurus-dark">
          <Trans id="auth.toLogin" />
        </Link>
      }
    >
      {household ? (
        <ChildLoginForm
          pending={childLogin.isPending}
          error={error}
          onSubmit={({ username, pin }) => {
            setError(null);
            childLogin.mutate(
              { household_id: household, username, pin },
              {
                onSuccess: () => navigate({ to: "/" }),
                onError: (err) => {
                  const slug = err instanceof ProblemError ? err.slug : "error";
                  setError(ERROR_KEYS[slug] ?? "state.error");
                },
              },
            );
          }}
        />
      ) : (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id="child.login.noHousehold" />
        </p>
      )}
    </AuthShell>
  );
}
