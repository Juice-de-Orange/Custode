import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

export type ChildCreateValues = { display_name: string; username: string; pin: string };

type ChildCreateFormProps = {
  onSubmit: (values: ChildCreateValues) => void;
  pending: boolean;
  error: string | null; // i18n key, or null
  createdName: string | null; // username of the just-created child, or null
};

// Pure admin form to create a child account (display name + household-unique username + 4-6 digit
// PIN). The account page wires the mutation and maps slugs (username_taken / weak_pin) to errors.
export function ChildCreateForm({ onSubmit, pending, error, createdName }: ChildCreateFormProps) {
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [pin, setPin] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({ display_name: displayName, username, pin });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      <Field
        id="child-name"
        required
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
        label={<Trans id="child.displayName" />}
      />
      <Field
        id="child-username"
        required
        value={username}
        onChange={(event) => setUsername(event.target.value)}
        label={<Trans id="child.username" />}
      />
      <Field
        id="child-pin"
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
      {createdName ? (
        <p role="status" className="text-sm text-laurus dark:text-laurus-dark">
          <Trans id="child.created" /> {createdName}
        </p>
      ) : null}
      <Button type="submit" disabled={pending}>
        <Trans id="child.create" />
      </Button>
    </form>
  );
}
