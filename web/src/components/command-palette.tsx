import * as Dialog from "@radix-ui/react-dialog";
import { useLingui } from "@lingui/react";
import { useNavigate } from "@tanstack/react-router";
import { Download, Plus, Search, ShieldCheck, UserCog, type LucideIcon } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { NAV_GROUPS } from "../lib/nav";

// The first real Radix overlay in the app (UX_KONZEPT §2, plan Slice 5): a ⌘/Ctrl+K command palette
// that jumps to any module + a few quick actions. Built as an accessible combobox (aria-activedescendant
// pattern) so the keyboard drives selection while focus stays on the search input. Radix Dialog gives
// the focus trap, scrim, Escape-to-close and aria-modal wiring the rest of the app's overlays reuse.

export type Command = {
  id: string;
  label: string;
  /** Muted right-aligned section label (e.g. the nav group), also searchable. */
  hint?: string;
  icon: LucideIcon;
  run: () => void;
};

// Platform-aware modifier glyph for the visible ⌘K / Ctrl K affordance.
export const IS_MAC =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent || "");

function norm(s: string): string {
  return s.toLowerCase().trim();
}

// Router-free presentation + interaction, so it can be axe-tested without a router (see a11y.test).
export function CommandDialog({
  open,
  onOpenChange,
  commands,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  commands: Command[];
}) {
  const { i18n } = useLingui();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listId = useId();
  const optionId = (i: number) => `${listId}-opt-${i}`;

  const filtered = useMemo(() => {
    const q = norm(query);
    if (!q) return commands;
    return commands.filter(
      (c) => norm(c.label).includes(q) || (c.hint ? norm(c.hint).includes(q) : false),
    );
  }, [commands, query]);

  const hasResults = filtered.length > 0;
  const activeIndex = hasResults ? Math.min(active, filtered.length - 1) : 0;

  // Reset transient state whenever the palette closes — covers EVERY close path (Radix Escape/
  // outside-click, ⌘K toggle from the parent, and selecting a command), so it reopens fresh.
  useEffect(() => {
    if (!open) {
      setQuery("");
      setActive(0);
    }
  }, [open]);

  function select(cmd: Command) {
    onOpenChange(false);
    cmd.run();
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (hasResults) setActive((a) => (a + 1) % filtered.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (hasResults) setActive((a) => (a - 1 + filtered.length) % filtered.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (hasResults) select(filtered[activeIndex]);
    }
    // Escape is handled by Radix (closes the dialog).
  }

  // Keep the active option scrolled into view (guarded: jsdom lacks scrollIntoView).
  useEffect(() => {
    if (open && hasResults) {
      document.getElementById(optionId(activeIndex))?.scrollIntoView?.({ block: "nearest" });
    }
    // optionId is stable via the constant listId; re-run when the selection or result set changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeIndex, open, hasResults]);

  const title = i18n._("command.title");
  const placeholder = i18n._("command.placeholder");

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-tinte/40 backdrop-blur-sm dark:bg-nacht/70" />
        <Dialog.Content
          onOpenAutoFocus={(e) => {
            e.preventDefault();
            inputRef.current?.focus();
          }}
          className="fixed left-1/2 top-[14vh] z-50 w-[min(92vw,34rem)] -translate-x-1/2 overflow-hidden rounded-card border border-stein/15 bg-papier shadow-elev dark:border-stein/20 dark:bg-nacht-2"
        >
          <Dialog.Title className="sr-only">{title}</Dialog.Title>
          <Dialog.Description className="sr-only">{placeholder}</Dialog.Description>
          <div className="flex items-center gap-2 border-b border-stein/15 px-4">
            <Search className="size-4 shrink-0 text-stein-text" aria-hidden="true" />
            <input
              ref={inputRef}
              type="text"
              role="combobox"
              aria-expanded={hasResults}
              aria-controls={hasResults ? listId : undefined}
              aria-activedescendant={hasResults ? optionId(activeIndex) : undefined}
              aria-autocomplete="list"
              aria-label={placeholder}
              placeholder={placeholder}
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              className="w-full bg-transparent py-3.5 text-base text-tinte placeholder:text-stein-text dark:text-kalk md:text-sm"
            />
          </div>
          {/* Announce the result state to assistive tech (WCAG 4.1.3): the aria-activedescendant
              pattern only conveys the active option, never the count or the empty result. Polite so
              it never interrupts typing. */}
          <div role="status" aria-live="polite" className="sr-only">
            {hasResults ? i18n._("command.results", { count: filtered.length }) : i18n._("command.empty")}
          </div>
          {hasResults ? (
            // A listbox contains role=option children directly (no <li> — a role on <ul> would
            // orphan its list items). Buttons keep it lint-clean/native-interactive; tabIndex=-1
            // keeps them out of the tab order so the input's aria-activedescendant drives selection.
            <div
              id={listId}
              role="listbox"
              aria-label={title}
              className="max-h-[min(58vh,24rem)] overflow-y-auto p-2"
            >
              {filtered.map((cmd, i) => {
                const Icon = cmd.icon;
                const selected = i === activeIndex;
                return (
                  <button
                    key={cmd.id}
                    type="button"
                    id={optionId(i)}
                    role="option"
                    aria-selected={selected}
                    tabIndex={-1}
                    onClick={() => select(cmd)}
                    onPointerMove={() => setActive(i)}
                    className={`flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm transition-colors ${
                      selected
                        ? "bg-laurus/10 text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark"
                        : "text-tinte hover:bg-stein/10 dark:text-kalk dark:hover:bg-kalk/10"
                    }`}
                  >
                    <Icon className="size-4 shrink-0" strokeWidth={1.75} aria-hidden="true" />
                    <span className="flex-1 truncate">{cmd.label}</span>
                    {cmd.hint ? <span className="shrink-0 text-xs text-stein-text">{cmd.hint}</span> : null}
                  </button>
                );
              })}
            </div>
          ) : (
            <p className="px-4 py-10 text-center text-sm text-stein-text">{i18n._("command.empty")}</p>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

// Wired palette: builds the command list from the shared nav model + a few quick actions, and owns the
// global ⌘/Ctrl+K hotkey + the mobile floating trigger. Mounted once by the signed-in shell.
export function CommandPalette({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { i18n } = useLingui();
  const navigate = useNavigate();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  const commands = useMemo<Command[]>(() => {
    const go = (to: string) => () => void navigate({ to });
    const nav: Command[] = NAV_GROUPS.flatMap((group) =>
      group.items.map((item) => ({
        id: `nav:${item.to}`,
        label: i18n._(item.labelKey),
        hint: i18n._(group.labelKey),
        icon: item.icon,
        run: go(item.to),
      })),
    );
    const accountHint = i18n._("nav.group.account");
    const extras: Command[] = [
      { id: "nav:/profile", label: i18n._("profile.title"), hint: accountHint, icon: UserCog, run: go("/profile") },
      { id: "nav:/security", label: i18n._("security.title"), hint: accountHint, icon: ShieldCheck, run: go("/security") },
    ];
    const actionsHint = i18n._("command.section.actions");
    const actions: Command[] = [
      { id: "act:new-recipe", label: i18n._("recipe.new"), hint: actionsHint, icon: Plus, run: go("/recipes/new") },
      { id: "act:import-recipe", label: i18n._("recipe.import.link"), hint: actionsHint, icon: Download, run: go("/recipes/import") },
    ];
    return [...nav, ...extras, ...actions];
  }, [i18n, navigate]);

  return (
    <>
      <CommandDialog open={open} onOpenChange={onOpenChange} commands={commands} />
      {/* Mobile: a floating trigger since the sidebar search button is desktop-only. z-30 keeps it
          above page content but BELOW the bottom bar's z-40 „Mehr" sheet + scrim, so the open sheet
          covers it instead of the FAB painting on top. */}
      <button
        type="button"
        aria-label={i18n._("command.open")}
        onClick={() => onOpenChange(true)}
        className="fixed bottom-above-bar right-4 z-30 flex size-12 items-center justify-center rounded-pill bg-laurus text-kalk shadow-elev transition-transform hover:scale-105 active:scale-95 dark:bg-laurus-dark dark:text-nacht md:hidden"
      >
        <Search className="size-5" aria-hidden="true" />
      </button>
    </>
  );
}
