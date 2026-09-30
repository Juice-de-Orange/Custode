import { Trans } from "@lingui/react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import type { TotpSetupResponse } from "../api/types.gen";
import {
  ProblemError,
  useDeletePasskey,
  useLoginEvents,
  usePasskeys,
  useRegenerateRecoveryCodes,
  useRegisterPasskey,
  useRevokeSession,
  useSession,
  useSessions,
  useTotpDisable,
  useTotpEnable,
  useTotpSetup,
} from "../auth/session";
import { passkeysSupported } from "../auth/webauthn";
import { LoginActivity } from "../components/login-activity";
import { PasskeyManager } from "../components/passkey-manager";
import { SessionsList } from "../components/sessions-list";
import { ErrorState, LoadingState } from "../components/states";
import { TotpSetup } from "../components/totp-setup";

const TOTP_ERRORS: Record<string, string> = {
  totp_invalid: "security.error.totpInvalid",
  totp_already_enabled: "security.error.totpSetupAgain",
  totp_not_set_up: "security.error.totpSetupAgain",
  totp_not_enabled: "security.error.totpNotEnabled",
};

const PASSKEY_ERRORS: Record<string, string> = {
  passkey_exists: "security.error.passkeyExists",
  passkey_cancelled: "security.error.passkeyCancelled",
};

function slugOf(err: unknown): string {
  return err instanceof ProblemError ? err.slug : "error";
}

// Protected self-service security center (KONZEPT §8): TOTP enrollment (QR + recovery codes) and
// passkey management, on top of the existing auth backend. Redirects to /login without a session.
export function SecurityPage() {
  const navigate = useNavigate();
  const { data, isLoading, isError } = useSession();

  const totpSetup = useTotpSetup();
  const totpEnable = useTotpEnable();
  const totpDisable = useTotpDisable();
  const regenerate = useRegenerateRecoveryCodes();
  const passkeys = usePasskeys();
  const registerPasskey = useRegisterPasskey();
  const deletePasskey = useDeletePasskey();
  const sessions = useSessions();
  const revokeSession = useRevokeSession();
  const loginEvents = useLoginEvents();

  const [setupData, setSetupData] = useState<TotpSetupResponse | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [totpError, setTotpError] = useState<string | null>(null);
  const [passkeyError, setPasskeyError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoading && data === null) navigate({ to: "/login" });
  }, [isLoading, data, navigate]);

  if (isLoading || data === null) return <LoadingState />;
  if (isError || data === undefined) return <ErrorState />;

  const startSetup = () => {
    setTotpError(null);
    totpSetup.mutate(undefined, {
      onSuccess: (res) => setSetupData(res),
      onError: (err) => setTotpError(TOTP_ERRORS[slugOf(err)] ?? "state.error"),
    });
  };

  const enable = (code: string) => {
    setTotpError(null);
    totpEnable.mutate(code, {
      onSuccess: (res) => {
        setSetupData(null);
        setRecoveryCodes(res.recovery_codes);
      },
      onError: (err) => setTotpError(TOTP_ERRORS[slugOf(err)] ?? "state.error"),
    });
  };

  const disable = (code: string) => {
    setTotpError(null);
    totpDisable.mutate(code, {
      onError: (err) => setTotpError(TOTP_ERRORS[slugOf(err)] ?? "state.error"),
    });
  };

  const regenerateCodes = () => {
    setTotpError(null);
    regenerate.mutate(undefined, {
      onSuccess: (res) => setRecoveryCodes(res.recovery_codes),
      onError: (err) => setTotpError(TOTP_ERRORS[slugOf(err)] ?? "state.error"),
    });
  };

  const addPasskey = (name: string) => {
    setPasskeyError(null);
    registerPasskey.mutate(name, {
      onError: (err) => {
        const slug = slugOf(err);
        if (slug === "passkey_cancelled") return; // user aborted the ceremony — not worth surfacing
        setPasskeyError(PASSKEY_ERRORS[slug] ?? "security.error.passkeyAdd");
      },
    });
  };

  return (
    <section aria-labelledby="security-heading" className="mx-auto max-w-lg space-y-10">
      <div className="space-y-2">
        <h1 id="security-heading" className="font-display text-2xl">
          <Trans id="security.title" />
        </h1>
        <Link to="/" className="text-sm text-laurus dark:text-laurus-dark hover:underline">
          <Trans id="security.back" />
        </Link>
      </div>

      <div className="space-y-4">
        <h2 className="font-display text-xl">
          <Trans id="security.twoFactor.title" />
        </h2>
        <TotpSetup
          enabled={data.totp_enabled}
          setupData={setupData}
          recoveryCodes={recoveryCodes}
          error={totpError}
          setupPending={totpSetup.isPending}
          enablePending={totpEnable.isPending}
          disablePending={totpDisable.isPending}
          regeneratePending={regenerate.isPending}
          onSetup={startSetup}
          onEnable={enable}
          onDisable={disable}
          onRegenerate={regenerateCodes}
          onAcknowledgeCodes={() => setRecoveryCodes(null)}
        />
        {data.totp_enabled && !recoveryCodes ? (
          <p className="text-sm text-stein-text">
            <Trans id="security.recovery.remaining" /> {data.recovery_codes_remaining}
          </p>
        ) : null}
      </div>

      <div className="space-y-4">
        <h2 className="font-display text-xl">
          <Trans id="security.passkeys.title" />
        </h2>
        <PasskeyManager
          passkeys={passkeys.data ?? []}
          loading={passkeys.isLoading}
          isError={passkeys.isError}
          supported={passkeysSupported()}
          error={passkeyError}
          addPending={registerPasskey.isPending}
          deletePendingId={deletePasskey.isPending ? (deletePasskey.variables ?? null) : null}
          onAdd={addPasskey}
          onDelete={(id) => {
            setPasskeyError(null);
            deletePasskey.mutate(id, {
              onError: (err) => setPasskeyError(PASSKEY_ERRORS[slugOf(err)] ?? "state.error"),
            });
          }}
        />
      </div>

      <div className="space-y-4">
        <h2 className="font-display text-xl">
          <Trans id="security.sessions.title" />
        </h2>
        <SessionsList
          sessions={sessions.data ?? []}
          loading={sessions.isLoading}
          isError={sessions.isError}
          revokePendingId={revokeSession.isPending ? (revokeSession.variables ?? null) : null}
          onRevoke={(id) => revokeSession.mutate(id)}
        />
      </div>

      <div className="space-y-4">
        <h2 className="font-display text-xl">
          <Trans id="security.activity.title" />
        </h2>
        <LoginActivity
          events={loginEvents.data ?? []}
          loading={loginEvents.isLoading}
          isError={loginEvents.isError}
        />
      </div>
    </section>
  );
}
