import { BRAND_NAME } from "../lib/brand";

// The keeper's-arch emblem (ADR-0075): an arched doorway with a keyhole — „Custode" = guardian of
// the home. Monoline, drawn in currentColor so it inherits the brand green (text-laurus). Purely
// decorative; aria-hidden — the wordmark next to it carries the accessible name.
export function BrandLogomark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" className={className}>
      <path
        d="M6 29V14a10 10 0 0 1 20 0v15"
        stroke="currentColor"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="16" cy="14.5" r="2.7" fill="currentColor" />
      <path d="M16 16.7 14.7 22h2.6z" fill="currentColor" />
    </svg>
  );
}

// Logomark + wordmark lock-up. BRAND_NAME stays the single source of the displayed name
// (web/src/lib/brand.ts) — never hardcode it (CLAUDE.md). Used in the app shell + ops console.
export function BrandMark({
  className,
  markClassName = "size-6 text-laurus dark:text-laurus-dark",
  wordClassName = "font-display text-lg font-semibold tracking-tight",
}: {
  className?: string;
  markClassName?: string;
  wordClassName?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${className ?? ""}`}>
      <BrandLogomark className={markClassName} />
      <span className={wordClassName}>{BRAND_NAME}</span>
    </span>
  );
}
