import { Trans } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";

import { useConfirmEmail } from "../auth/session";
import { AuthShell } from "../components/auth-shell";
import { LoadingState } from "../components/states";

// Confirm an e-mail address from a verification link (?token=...). Runs the confirm once on mount;
// the ref guards against React's double-invoke in dev StrictMode.
export function VerifyEmailPage() {
  const confirm = useConfirmEmail();
  const [status, setStatus] = useState<"pending" | "done" | "error">("pending");
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const token = new URLSearchParams(window.location.search).get("token") ?? "";
    confirm.mutate(token, {
      onSuccess: () => setStatus("done"),
      onError: () => setStatus("error"),
    });
  }, [confirm]);

  return (
    <AuthShell
      title={<Trans id="verify.title" />}
      footer={
        <Link to="/" className="text-laurus hover:underline dark:text-laurus-dark">
          <Trans id="verify.toAccount" />
        </Link>
      }
    >
      {status === "pending" ? <LoadingState /> : null}
      {status === "done" ? (
        <p role="status" className="text-laurus dark:text-laurus-dark">
          <Trans id="verify.done" />
        </p>
      ) : null}
      {status === "error" ? (
        <p role="alert" className="text-bernstein-text dark:text-bernstein">
          <Trans id="verify.error" />
        </p>
      ) : null}
    </AuthShell>
  );
}
