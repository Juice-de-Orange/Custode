import { Trans } from "@lingui/react";
import { Inbox, Loader2, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";

// The Trio (ENTWICKLUNGSKONZEPT DoD): every route provides Loading, Empty, Error. „Kino-Ruhe"
// (ADR-0075): warmer than a grey box — a quiet icon, a centered message, and (empty) the next
// sensible step (Produktprinzip P7). Icons are decorative (aria-hidden); the text carries meaning.
export function LoadingState() {
  return (
    <div role="status" aria-live="polite" className="flex items-center gap-2 text-stein-text">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" aria-hidden="true" />
      <Trans id="state.loading" />
    </div>
  );
}

export function EmptyState({
  icon,
  action,
  children,
}: {
  // Optional module-specific glyph + a „nächster sinnvoller Schritt"-CTA (P7).
  icon?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-card border border-stein/25 bg-papier/50 px-6 py-8 text-center dark:bg-nacht-2/50">
      <span className="text-stein-text/70" aria-hidden="true">
        {icon ?? <Inbox className="size-7" strokeWidth={1.5} />}
      </span>
      <div className="text-sm text-stein-text">{children ?? <Trans id="today.empty" />}</div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ reference }: { reference?: string }) {
  // Human message + handling option + copyable reference code (UX_KONZEPT §6).
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-card border border-rost/40 bg-rost/5 p-5"
    >
      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-rost" aria-hidden="true" />
      <div>
        <p>
          <Trans id="state.error" />
        </p>
        {reference ? <p className="mt-1 font-mono text-sm text-stein-text">{reference}</p> : null}
      </div>
    </div>
  );
}
