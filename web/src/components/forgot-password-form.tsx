import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

type ForgotPasswordFormProps = {
  onSubmit: (email: string) => void;
  pending: boolean;
  submitted: boolean; // after a submit we always show the same generic message (no enumeration)
};

export function ForgotPasswordForm({ onSubmit, pending, submitted }: ForgotPasswordFormProps) {
  const [email, setEmail] = useState("");

  if (submitted) {
    return (
      <p role="status" className="text-sm text-stein-text">
        <Trans id="auth.forgot.sent" />
      </p>
    );
  }

  return (
    <form
      onSubmit={(event: FormEvent) => {
        event.preventDefault();
        onSubmit(email);
      }}
      className="space-y-4"
      noValidate
    >
      <Field
        id="forgot-email"
        type="email"
        autoComplete="email"
        required
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        label={<Trans id="auth.email" />}
      />
      <Button type="submit" disabled={pending} className="w-full justify-center">
        <Trans id="auth.forgot.submit" />
      </Button>
    </form>
  );
}
