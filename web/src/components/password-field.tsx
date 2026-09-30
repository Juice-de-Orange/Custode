import { Trans } from "@lingui/react";
import { type ComponentPropsWithoutRef, type ReactNode, useState } from "react";

type PasswordFieldProps = Omit<ComponentPropsWithoutRef<"input">, "type" | "id"> & {
  id: string;
  label: ReactNode;
};

// Password input with a show/hide toggle. The toggle swaps the input type between
// "password" and "text"; it is type="button" so it never submits the form and exposes
// its state via aria-pressed + aria-controls for assistive tech. Styling mirrors Field
// (kalk/tinte/stein/laurus tokens) with right padding to clear the toggle.
export function PasswordField({ id, label, className = "", ...props }: PasswordFieldProps) {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-tinte dark:text-kalk">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={revealed ? "text" : "password"}
          className={`block w-full rounded-md border border-stein/40 bg-papier px-3 py-2 pr-24 text-tinte placeholder:text-stein-text/60 focus:border-laurus focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:border-stein/25 dark:bg-nacht-2 dark:text-kalk dark:focus:border-laurus-dark dark:focus:ring-laurus-dark/40 ${className}`}
          {...props}
        />
        <button
          type="button"
          onClick={() => setRevealed((value) => !value)}
          aria-controls={id}
          aria-pressed={revealed}
          className="absolute inset-y-0 right-0 flex items-center rounded-md px-3 text-sm font-medium text-stein-text hover:text-tinte focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:hover:text-kalk"
        >
          <Trans id={revealed ? "auth.hidePassword" : "auth.showPassword"} />
        </button>
      </div>
    </div>
  );
}
