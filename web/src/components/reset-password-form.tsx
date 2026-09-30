import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { PasswordField } from "./password-field";

type ResetPasswordFormProps = {
  onSubmit: (password: string) => void;
  pending: boolean;
  error: string | null; // i18n key, or null
  done: boolean; // success — show a confirmation instead of the form
};

export function ResetPasswordForm({ onSubmit, pending, error, done }: ResetPasswordFormProps) {
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);

  if (done) {
    return (
      <p role="status" className="text-sm text-laurus dark:text-laurus-dark">
        <Trans id="auth.reset.done" />
      </p>
    );
  }

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (password !== confirm) {
      setMismatch(true); // catch typos before hitting the server
      return;
    }
    setMismatch(false);
    onSubmit(password);
  };

  const shownError = mismatch ? "auth.error.passwordMismatch" : error;

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <PasswordField
        id="reset-password"
        autoComplete="new-password"
        required
        minLength={10}
        value={password}
        onChange={(event) => {
          setPassword(event.target.value);
          setMismatch(false);
        }}
        label={<Trans id="auth.password" />}
      />
      <PasswordField
        id="reset-password-confirm"
        autoComplete="new-password"
        required
        minLength={10}
        value={confirm}
        aria-invalid={mismatch}
        onChange={(event) => {
          setConfirm(event.target.value);
          setMismatch(false);
        }}
        label={<Trans id="auth.passwordConfirm" />}
      />
      {shownError ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={shownError} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending} className="w-full justify-center">
        <Trans id="auth.reset.submit" />
      </Button>
    </form>
  );
}
