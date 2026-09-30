import { Slot } from "@radix-ui/react-slot";
import type { ComponentPropsWithoutRef, ElementType } from "react";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

type ButtonProps = ComponentPropsWithoutRef<"button"> & {
  asChild?: boolean;
  variant?: Variant;
  size?: Size;
};

const base =
  "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-all disabled:pointer-events-none";

// coarse: (touch) minimum heights approach the 44 px guideline (UX_KONZEPT §7) without
// changing desktop density — pointer devices keep the compact paddings.
const sizes: Record<Size, string> = {
  sm: "px-3 py-1.5 text-sm coarse:min-h-10",
  md: "px-4 py-2 coarse:min-h-11",
};

// Disabled states are explicit colors instead of opacity-50: fading the whole button dropped the
// label below AA in light mode (white on light sage ~2:1). --color-stein-text is theme-switched,
// so the muted label clears ~4.5:1 on both the light (nebel) and dark (nacht-2) disabled fill.
const variants: Record<Variant, string> = {
  // The one filled element: the brand green with a little cinematic depth on hover.
  primary:
    "bg-laurus text-kalk shadow-soft hover:bg-laurus-dark hover:shadow-elev disabled:bg-nebel disabled:text-stein-text disabled:shadow-none dark:bg-laurus-dark dark:text-nacht dark:disabled:bg-nacht-2 dark:disabled:text-stein-text",
  // Quiet outlined action in the brand green (replaces the hand-rolled secondary buttons across
  // the app). Outline vs. fill keeps the primary/secondary hierarchy visible in both themes.
  secondary:
    "border border-laurus text-laurus hover:bg-laurus/10 disabled:border-stein/40 disabled:text-stein-text dark:border-laurus-dark dark:text-laurus-dark dark:hover:bg-laurus-dark/15 dark:disabled:border-stein/40 dark:disabled:text-stein-text",
  ghost:
    "text-laurus hover:bg-laurus/10 disabled:text-stein-text dark:text-laurus-dark dark:hover:bg-laurus-dark/15 dark:disabled:text-stein-text",
  // Destructive actions (delete): rost is the design language's „rot"-signal (ADR-0075) — bernstein
  // is reserved for reward moments. The kalk label clears AA (~5.6:1) on the muted brick red, and the
  // same fill serves both themes, so no dark: utility can override it (the old per-call-site
  // bg-bernstein className lost exactly that fight, CHANGELOG #134).
  danger:
    "bg-rost text-kalk shadow-soft hover:bg-rost/90 hover:shadow-elev disabled:bg-nebel disabled:text-stein-text disabled:shadow-none dark:disabled:bg-nacht-2 dark:disabled:text-stein-text",
};

// Radix Slot as the base of the component library (ADR-007). `asChild` renders as a link etc. while
// keeping styling. Default variant/size keep every existing call-site visually stable.
export function Button({
  asChild = false,
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonProps) {
  const Comp: ElementType = asChild ? Slot : "button";
  return <Comp className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props} />;
}
