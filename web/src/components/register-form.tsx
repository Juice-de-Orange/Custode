import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";
import { PasswordField } from "./password-field";

export type RegisterValues = { email: string; password: string; display_name: string };

type RegisterFormProps = {
  onSubmit: (values: RegisterValues) => void;
  pending: boolean;
  error: string | null; // i18n key, or null
};

export function RegisterForm({ onSubmit, pending, error }: RegisterFormProps) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [mismatch, setMismatch] = useState(false);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setMismatch(true); // catch typos before hitting the server
      return;
    }
    setMismatch(false);
    onSubmit({ email, password, display_name: displayName });
  };

  // Editing either password field clears the local mismatch so the alert never lingers.
  const onPasswordChange = (value: string) => {
    setPassword(value);
    setMismatch(false);
  };
  const onConfirmChange = (value: string) => {
    setConfirm(value);
    setMismatch(false);
  };

  const shownError = mismatch ? "auth.error.passwordMismatch" : error;

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Field
        id="reg-name"
        autoComplete="name"
        required
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
        label={<Trans id="auth.name" />}
      />
      <Field
        id="reg-email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        label={<Trans id="auth.email" />}
      />
      <PasswordField
        id="reg-password"
        autoComplete="new-password"
        required
        minLength={10}
        value={password}
        onChange={(event) => onPasswordChange(event.target.value)}
        label={<Trans id="auth.password" />}
      />
      <PasswordField
        id="reg-password-confirm"
        autoComplete="new-password"
        required
        minLength={10}
        value={confirm}
        aria-invalid={mismatch}
        onChange={(event) => onConfirmChange(event.target.value)}
        label={<Trans id="auth.passwordConfirm" />}
      />
      {shownError ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={shownError} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending} className="w-full">
        <Trans id="auth.register" />
      </Button>
    </form>
  );
}
