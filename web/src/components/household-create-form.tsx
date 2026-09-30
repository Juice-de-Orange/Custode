import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

type Props = {
  onSubmit: (name: string) => void;
  pending: boolean;
  error: string | null;
};

export function HouseholdCreateForm({ onSubmit, pending, error }: Props) {
  const [name, setName] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(name);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      <Field
        id="hh-name"
        required
        value={name}
        onChange={(event) => setName(event.target.value)}
        label={<Trans id="household.name" />}
      />
      {error ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending}>
        <Trans id="household.create" />
      </Button>
    </form>
  );
}
