import { useId, type ReactNode } from "react";

import { BrandMark } from "./brand-mark";
import { LandscapeScene } from "./scenes/landscape-scene";

// Poster-style wrapper for the auth screens (ADR-0075): a cinematic scene banner carries the brand
// + title, the form sits on a calm card below. The scrim keeps the title AA-legible over the scene
// (Farbe nie alleiniger Träger). Dark-aware throughout.
export function AuthShell({
  title,
  children,
  footer,
}: {
  title: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
}) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      className="mx-auto max-w-md overflow-hidden rounded-card border border-stein/15 bg-papier shadow-elev dark:border-stein/15 dark:bg-nacht-2"
    >
      <div className="relative h-44 overflow-hidden">
        <LandscapeScene className="absolute inset-0 size-full" />
        <div className="scrim-b absolute inset-0" />
        <div className="absolute inset-x-0 bottom-0 flex flex-col gap-1 p-5 text-tinte dark:text-kalk">
          <BrandMark
            markClassName="size-5 text-laurus dark:text-laurus-dark"
            wordClassName="font-display text-sm font-semibold tracking-tight"
          />
          <h1 id={headingId} className="font-display text-2xl font-semibold tracking-tight">
            {title}
          </h1>
        </div>
      </div>
      <div className="space-y-5 p-6">
        {children}
        {footer ? <div className="flex flex-col gap-1 text-sm">{footer}</div> : null}
      </div>
    </section>
  );
}
