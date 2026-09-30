import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useState } from "react";

import { ProblemError, useLogin, usePasskeyLogin } from "../auth/session";
import { passkeysSupported } from "../auth/webauthn";
import { AuthShell } from "../components/auth-shell";
import { LoginForm, type LoginValues } from "../components/login-form";

const ERROR_KEYS: Record<string, string> = {
  invalid_credentials: "auth.error.credentials",
  totp_required: "auth.error.totp",
};

const PASSKEY_ERROR_KEYS: Record<string, string> = {
  passkey_cancelled: "auth.error.passkeyCancelled",
};

export function LoginPage() {
  const navigate = useNavigate();
  const login = useLogin();
  const passkey = usePasskeyLogin();
  const [totpRequired, setTotpRequired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const supported = passkeysSupported();

  const onSubmit = (values: LoginValues) => {
    setError(null);
    login.mutate(values, {
      onSuccess: () => navigate({ to: "/" }),
      onError: (err) => {
        const slug = err instanceof ProblemError ? err.slug : "error";
        if (slug === "totp_required") setTotpRequired(true);
        setError(ERROR_KEYS[slug] ?? "state.error");
      },
    });
  };

  const onPasskey = () => {
    setError(null);
    passkey.mutate(undefined, {
      onSuccess: () => navigate({ to: "/" }),
      onError: (err) => {
        const slug = err instanceof ProblemError ? err.slug : "error";
        setError(PASSKEY_ERROR_KEYS[slug] ?? "auth.error.passkey");
      },
    });
  };

  return (
    <AuthShell
      title={<Trans id="auth.login.title" />}
      footer={
        <>
          <Link to="/register" className="text-laurus hover:underline dark:text-laurus-dark">
            <Trans id="auth.toRegister" />
          </Link>
          <Link
            to="/forgot-password"
            className="text-laurus hover:underline dark:text-laurus-dark"
          >
            <Trans id="auth.forgot.link" />
          </Link>
        </>
      }
    >
      <LoginForm
        onSubmit={onSubmit}
        pending={login.isPending}
        totpRequired={totpRequired}
        error={error}
        onPasskey={onPasskey}
        passkeySupported={supported}
        passkeyPending={passkey.isPending}
      />
    </AuthShell>
  );
}
