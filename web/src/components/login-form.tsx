import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";
import { PasswordField } from "./password-field";

export type LoginValues = {
  email: string;
  password: string;
  totp_code?: string;
  recovery_code?: string;
};

type LoginFormProps = {
  onSubmit: (values: LoginValues) => void;
  pending: boolean;
  totpRequired: boolean;
  error: string | null; // i18n key, or null
  onPasskey?: () => void; // passwordless login; the route wires the ceremony + navigation
  passkeySupported?: boolean; // window.PublicKeyCredential present
  passkeyPending?: boolean;
};

// Pure login form (no router/query) so it stays trivially testable; the route wires the
// mutation + navigation. Once the server asks for the second factor it shows a TOTP field
// (with a fallback to a recovery code), and offers passwordless login when the browser
// supports it.
export function LoginForm({
  onSubmit,
  pending,
  totpRequired,
  error,
  onPasskey,
  passkeySupported = false,
  passkeyPending = false,
}: LoginFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [recoveryCode, setRecoveryCode] = useState("");
  const [recoveryMode, setRecoveryMode] = useState(false);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (totpRequired && recoveryMode) {
      onSubmit({ email, password, recovery_code: recoveryCode });
    } else {
      onSubmit({ email, password, totp_code: totpRequired ? totpCode : undefined });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Field
        id="email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        label={<Trans id="auth.email" />}
      />
      <PasswordField
        id="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        label={<Trans id="auth.password" />}
      />
      {totpRequired ? (
        <div className="space-y-2">
          {recoveryMode ? (
            <Field
              id="recovery_code"
              autoComplete="one-time-code"
              required
              value={recoveryCode}
              onChange={(event) => setRecoveryCode(event.target.value)}
              label={<Trans id="auth.recoveryCode" />}
            />
          ) : (
            <Field
              id="totp_code"
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={totpCode}
              onChange={(event) => setTotpCode(event.target.value)}
              label={<Trans id="auth.totp" />}
            />
          )}
          <button
            type="button"
            onClick={() => setRecoveryMode((on) => !on)}
            className="text-sm text-laurus hover:underline dark:text-laurus-dark"
          >
            <Trans id={recoveryMode ? "auth.useTotp" : "auth.useRecoveryCode"} />
          </button>
        </div>
      ) : null}
      {error ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending} className="w-full">
        <Trans id={totpRequired ? "auth.verify" : "auth.login"} />
      </Button>
      {onPasskey && passkeySupported ? (
        <Button
          type="button"
          variant="secondary"
          onClick={onPasskey}
          disabled={passkeyPending}
          className="w-full"
        >
          <Trans id="auth.passkey" />
        </Button>
      ) : null}
    </form>
  );
}
