import { Trans } from "@lingui/react";

import { Button } from "./button";

type VerificationBannerProps = {
  onResend: () => void;
  pending: boolean;
  sent: boolean; // after a resend we confirm instead of offering the button again
};

/** Whether the account has an e-mail address left to confirm. A child account has none (it signs
 *  in with username + PIN), so `email_verified` is false for it forever — asking it to confirm,
 *  with a "resend" button that has nowhere to send to, is noise. */
export function needsEmailVerification(me: { email: string | null; email_verified: boolean }): boolean {
  return !me.email_verified && !!me.email;
}

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
