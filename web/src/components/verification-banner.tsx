import { Trans } from "@lingui/react";

import { Button } from "./button";

type VerificationBannerProps = {
  onResend: () => void;
  pending: boolean;
  sent: boolean; // after a resend we confirm instead of offering the button again
};

// Shown on the account page while the user's e-mail is unverified (me.email_verified === false).
export function VerificationBanner({ onResend, pending, sent }: VerificationBannerProps) {
  return (
    <div role="status" className="space-y-2 rounded-md border border-bernstein/40 bg-bernstein/5 p-3 text-sm">
      <p>
        <Trans id="verify.banner.text" />
      </p>
      {sent ? (
        <p className="text-stein-text">
          <Trans id="verify.banner.resent" />
        </p>
      ) : (
        <Button type="button" variant="secondary" disabled={pending} onClick={onResend}>
          <Trans id="verify.banner.resend" />
        </Button>
      )}
    </div>
  );
}
