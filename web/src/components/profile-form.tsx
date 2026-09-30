import { Trans } from "@lingui/react";
import { type FormEvent, useState } from "react";

import { Button } from "./button";
import { Field } from "./field";

export type ProfileValues = { display_name: string; work_hours: string; dietary: string[] };

type ProfileFormProps = {
  initial: ProfileValues;
  onSubmit: (values: ProfileValues) => void;
  pending: boolean;
  error: string | null; // i18n key, or null
  saved: boolean;
};

// Pure profile editor. Dietary prefs are edited as a comma-separated list and parsed to an array on
// submit; the /profile route wires the query + If-Match update and maps a 412 conflict to an error.
export function ProfileForm({ initial, onSubmit, pending, error, saved }: ProfileFormProps) {
  const [displayName, setDisplayName] = useState(initial.display_name);
  const [workHours, setWorkHours] = useState(initial.work_hours);
  const [dietary, setDietary] = useState(initial.dietary.join(", "));

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onSubmit({
      display_name: displayName,
      work_hours: workHours,
      dietary: dietary
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      <Field
        id="profile-name"
        required
        value={displayName}
        onChange={(event) => setDisplayName(event.target.value)}
        label={<Trans id="auth.name" />}
      />
      <Field
        id="profile-hours"
        value={workHours}
        onChange={(event) => setWorkHours(event.target.value)}
        label={<Trans id="profile.workHours" />}
      />
      <Field
        id="profile-dietary"
        value={dietary}
        onChange={(event) => setDietary(event.target.value)}
        label={<Trans id="profile.dietary" />}
      />
      {error ? (
        <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      {saved ? (
        <p role="status" className="text-sm text-laurus dark:text-laurus-dark">
          <Trans id="profile.saved" />
        </p>
      ) : null}
      <Button type="submit" disabled={pending} className="w-full justify-center">
        <Trans id="profile.save" />
      </Button>
    </form>
  );
}
