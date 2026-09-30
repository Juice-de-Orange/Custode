import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

type Props = {
  onSubmit: (code: string) => void;
  pending: boolean;
  error: string | null;
};

export function HouseholdJoinForm({ onSubmit, pending, error }: Props) {
  const [code, setCode] = useState("");

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit(code);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      <Field
        id="hh-code"
        required
        value={code}
        onChange={(event) => setCode(event.target.value)}
        label={<Trans id="household.code" />}
      />
      {error ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      <Button type="submit" disabled={pending}>
        <Trans id="household.join" />
      </Button>
    </form>
  );
}
