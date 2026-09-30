import { Trans } from "@lingui/react";
import { QRCodeSVG } from "qrcode.react";
import { type FormEvent, useEffect, useRef, useState } from "react";

import type { TotpSetupResponse } from "../api/types.gen";
import { Button } from "./button";
import { Field } from "./field";

type TotpSetupProps = {
  enabled: boolean;
  setupData: TotpSetupResponse | null; // pending secret + otpauth URI for the QR
  recoveryCodes: string[] | null; // shown once after enable/regenerate
  error: string | null; // i18n key, or null
  setupPending: boolean;
  enablePending: boolean;
  disablePending: boolean;
  regeneratePending: boolean;
  onSetup: () => void;
  onEnable: (code: string) => void;
  onDisable: (code: string) => void;
  onRegenerate: () => void;
  onAcknowledgeCodes: () => void;
};

function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="text-sm text-bernstein-text dark:text-bernstein">
      <Trans id={error} />
    </p>
  );
}

// One-time recovery codes — never retrievable again, so we warn and offer a download. Focus
// moves to the heading on mount so a screen reader announces this critical step.
function RecoveryCodes({ codes, onAcknowledge }: { codes: string[]; onAcknowledge: () => void }) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    headingRef.current?.focus();
  }, []);
  const href = `data:text/plain;charset=utf-8,${encodeURIComponent(codes.join("\n"))}`;
  return (
    <div className="space-y-3">
      <h3 ref={headingRef} tabIndex={-1} className="font-medium">
        <Trans id="security.recovery.title" />
      </h3>
      <p className="text-sm text-bernstein-text dark:text-bernstein">
        <Trans id="security.recovery.warnOnce" />
      </p>
      <ul className="grid grid-cols-2 gap-1 font-mono text-sm">
        {codes.map((code) => (
          <li key={code} className="rounded bg-stein/10 px-2 py-1">
            {code}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3">
        <a
          href={href}
          download="custode-recovery-codes.txt"
          className="inline-flex items-center rounded-md border border-stein/40 px-4 py-2 text-sm hover:bg-stein/10 dark:hover:bg-kalk/10"
        >
          <Trans id="security.recovery.download" />
        </a>
        <Button type="button" onClick={onAcknowledge}>
          <Trans id="security.recovery.acknowledge" />
        </Button>
      </div>
    </div>
  );
}

// Self-service 2FA: setup → scan QR (or type the secret) → confirm a code → one-time recovery
// codes; once active, disable (with a code) or regenerate codes. Pure (no query/router) so the
// /security route wires the mutations and it stays trivially testable.
export function TotpSetup(props: TotpSetupProps) {
  const { enabled, setupData, recoveryCodes, error } = props;
  const [enableCode, setEnableCode] = useState("");
  const [disableCode, setDisableCode] = useState("");

  useEffect(() => {
    if (setupData) document.getElementById("totp-enable-code")?.focus();
  }, [setupData]);

  // Shown once right after enable or regenerate — takes precedence over the steady states.
  if (recoveryCodes) {
    return <RecoveryCodes codes={recoveryCodes} onAcknowledge={props.onAcknowledgeCodes} />;
  }

  if (!enabled) {
    if (!setupData) {
      return (
        <div className="space-y-3">
          <p className="text-sm text-stein-text">
            <Trans id="security.totp.inactive" />
          </p>
          <Button type="button" disabled={props.setupPending} onClick={props.onSetup}>
            <Trans id="security.totp.setup" />
          </Button>
        </div>
      );
    }
    return (
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          props.onEnable(enableCode);
        }}
      >
        <p className="text-sm text-stein-text">
          <Trans id="security.totp.scan" />
        </p>
        <QRCodeSVG
          value={setupData.otpauth_uri}
          size={180}
          aria-hidden
          className="rounded bg-kalk dark:bg-nacht-2 p-2"
        />
        <p className="text-sm">
          <Trans id="security.totp.manual" />{" "}
          <code className="rounded bg-stein/10 px-1.5 py-0.5 font-mono">{setupData.secret}</code>
        </p>
        <Field
          id="totp-enable-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          value={enableCode}
          onChange={(event) => setEnableCode(event.target.value)}
          label={<Trans id="security.totp.codeLabel" />}
        />
        <ErrorLine error={error} />
        <Button type="submit" disabled={props.enablePending}>
          <Trans id="security.totp.enable" />
        </Button>
      </form>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-laurus dark:text-laurus-dark">
        <Trans id="security.totp.active" />
      </p>
      <form
        className="space-y-3"
        noValidate
        onSubmit={(event: FormEvent) => {
          event.preventDefault();
          props.onDisable(disableCode);
        }}
      >
        <Field
          id="totp-disable-code"
          inputMode="numeric"
          autoComplete="one-time-code"
          required
          value={disableCode}
          onChange={(event) => setDisableCode(event.target.value)}
          label={<Trans id="security.totp.codeLabel" />}
        />
        <ErrorLine error={error} />
        <div className="flex flex-wrap gap-3">
          <Button type="submit" disabled={props.disablePending}>
            <Trans id="security.totp.disable" />
          </Button>
          <Button
            type="button"
            variant="secondary"
            disabled={props.regeneratePending}
            onClick={props.onRegenerate}
          >
            <Trans id="security.recovery.regenerate" />
          </Button>
        </div>
      </form>
    </div>
  );
}
