import type { ComponentPropsWithoutRef, ReactNode } from "react";

type FieldProps = ComponentPropsWithoutRef<"input"> & {
  id: string;
  label: ReactNode;
};

// Labeled text input. The label is associated via htmlFor/id (a11y); focus ring for
// keyboard users. Styling uses the Tailwind design tokens (kalk/tinte/stein/laurus).
export function Field({ id, label, className = "", ...props }: FieldProps) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-tinte dark:text-kalk">
        {label}
      </label>
      <input
        id={id}
        className={`block w-full rounded-md border border-stein/40 bg-papier px-3 py-2 text-tinte placeholder:text-stein-text/60 focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:border-stein/25 dark:bg-nacht-2 dark:text-kalk dark:focus:border-laurus-dark dark:focus:ring-laurus-dark/40 ${className}`}
        {...props}
      />
    </div>
  );
}
