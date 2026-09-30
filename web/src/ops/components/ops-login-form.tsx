import { Trans } from "@lingui/react";
import { useState } from "react";

import { Field } from "../../components/field";

export type OpsLoginValues = { email: string; password: string; totp_code: string };

type Props = {
  onSubmit: (values: OpsLoginValues) => void;
  pending: boolean;
  // i18n key of the current error, or null. TOTP is mandatory for operators (ADR-0072),
  // so the field is always shown (unlike the member login, where 2FA is optional).
  error: string | null;
};

// Pure, controlled operator-login form (e-mail + password + mandatory TOTP). Kept separate
// from the route so it is unit-/axe-testable without the router or a live mutation.
export function OpsLoginForm({ onSubmit, pending, error }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ email, password, totp_code: totpCode });
      }}
    >
      <Field
        id="ops-email"
        label={<Trans id="ops.login.email" />}
        type="email"
        autoComplete="username"
        required
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <Field
        id="ops-password"
        label={<Trans id="ops.login.password" />}
        type="password"
        autoComplete="current-password"
        required
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <Field
        id="ops-totp"
        label={<Trans id="ops.login.totp" />}
        inputMode="numeric"
        autoComplete="one-time-code"
        required
        value={totpCode}
        onChange={(e) => setTotpCode(e.target.value)}
      />
      {error ? (
        <p role="alert" className="text-sm text-bernstein">
          <Trans id={error} />
        </p>
      ) : null}
      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-md bg-laurus px-4 py-2 text-kalk hover:bg-laurus/90 focus:outline-none focus:ring-2 focus:ring-laurus/40 disabled:opacity-60"
      >
        <Trans id="ops.login.submit" />
      </button>
    </form>
  );
}
