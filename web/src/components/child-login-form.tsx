import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

export type ChildLoginValues = { username: string; pin: string };

type ChildLoginFormProps = {
  onSubmit: (values: ChildLoginValues) => void;
  pending: boolean;
  error: string | null; // i18n key, or null
};

// Pure child sign-in form (username + PIN). The household context comes from the route (?household=).
export function ChildLoginForm({ onSubmit, pending, error }: ChildLoginFormProps) {
  const [username, setUsername] = useState("");
  const [pin, setPin] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ username, pin });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Field
        id="child-login-username"
        required
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        label={<Trans id="child.username" />}
      />
      <Field
        id="child-login-pin"
        inputMode="numeric"
        autoComplete="off"
        required
        value={pin}
        onChange={(event) => setPin(event.target.value)}
        label={<Trans id="child.pin" />}
      />
      {error ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending} className="w-full justify-center">
        <Trans id="child.login.submit" />
      </Button>
    </form>
  );
}
