import { Trans } from "@lingui/react";
import { Link } from "@tanstack/react-router";
import { ChevronUp, Menu, Search, X } from "lucide-react";
import { useState } from "react";

import { i18n } from "../i18n";
import { MOBILE_PRIMARY, NAV_GROUPS, type NavItem } from "../lib/nav";
import { BrandMark } from "./brand-mark";
import { IS_MAC } from "./command-palette";
import { ThemeToggle } from "./theme-toggle";

const itemBase =
  "flex items-center gap-3 rounded-md px-3 py-2 text-sm text-tinte/80 transition-colors hover:bg-stein/10 dark:text-kalk/80 dark:hover:bg-kalk/10";
const itemActive = "bg-laurus/10 font-medium text-laurus dark:bg-laurus-dark/15 dark:text-laurus-dark";

function NavLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      onClick={onNavigate}
      activeOptions={item.to === "/" ? { exact: true } : undefined}
      className={itemBase}
      activeProps={{ className: itemActive }}
    >
      <Icon className="size-5 shrink-0" strokeWidth={1.75} aria-hidden="true" />
      <Trans id={item.labelKey} />
    </Link>
  );
}

// Desktop: a persistent, grouped sidebar with icons + active state (UX_KONZEPT §3). Hidden on
// mobile, where the bottom bar takes over. `onSearch` opens the ⌘K command palette.
export function AppSidebar({ onSearch }: { onSearch: () => void }) {
  return (
    <aside className="fixed left-0 top-0 z-30 hidden h-[100dvh] w-60 flex-col gap-5 overflow-y-auto border-r border-stein/15 bg-kalk px-3 py-5 dark:bg-nacht md:flex">
      <div className="flex items-center justify-between gap-2 px-2">
        <Link to="/today" className="text-tinte dark:text-kalk">
          <BrandMark />
        </Link>
        <ThemeToggle />
      </div>
      <button
        type="button"
        onClick={onSearch}
        className="mx-1 flex items-center gap-2 rounded-md border border-stein/25 bg-papier px-3 py-2 text-sm text-stein-text transition-colors hover:bg-stein/10 dark:border-stein/20 dark:bg-nacht-2 dark:hover:bg-kalk/10"
      >
        <Search className="size-4 shrink-0" aria-hidden="true" />
        <span className="flex-1 text-left">
          <Trans id="command.open" />
        </span>
        {/* Decorative shortcut hint — aria-hidden so the button names simply as „Suchen"; localized
            because the modifier is labelled „Strg" on German keyboards, not „Ctrl". */}
        <kbd
          aria-hidden="true"
          className="rounded border border-stein/30 px-1.5 py-0.5 font-mono text-[10px] text-stein-text dark:border-stein/25"
        >
          <Trans id={IS_MAC ? "command.shortcut.mac" : "command.shortcut.other"} />
        </kbd>
      </button>
      <nav aria-label="Hauptnavigation" className="flex flex-col gap-5">
        {NAV_GROUPS.map((group) => (
          <div key={group.labelKey} className="flex flex-col gap-0.5">
            <h2 className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-stein-text">
              <Trans id={group.labelKey} />
            </h2>
            {group.items.map((item) => (
              <NavLink key={item.to} item={item} />
            ))}
          </div>
        ))}
      </nav>
    </aside>
  );
}

// Mobile: a bottom-tab bar with the few primary destinations + a „Mehr" disclosure that reveals the
// full grouped navigation. Touch targets ≥ 44 px.
export function AppBottomBar() {
  const [moreOpen, setMoreOpen] = useState(false);
  const tab =
    "flex flex-1 flex-col items-center justify-center gap-0.5 py-2 text-[11px] text-tinte/70 dark:text-kalk/70";
  const tabActive = "text-laurus dark:text-laurus-dark";
  return (
    <>
      {moreOpen ? (
        <>
          <button
            type="button"
            aria-label={i18n._("nav.more.close")}
            onClick={() => setMoreOpen(false)}
            className="fixed inset-0 z-40 bg-tinte/40 md:hidden"
          />
          <div
            id="more-panel"
            className="fixed inset-x-0 bottom-bottom-bar z-40 max-h-[70dvh] overflow-y-auto rounded-t-card border-t border-stein/15 bg-papier px-4 pb-5 pt-4 shadow-elev dark:bg-nacht-2 md:hidden"
          >
            <div className="mb-3 flex items-center justify-between">
              <span className="font-display text-base font-semibold">
                <Trans id="nav.more" />
              </span>
              <button
                type="button"
                aria-label={i18n._("nav.more.close")}
                onClick={() => setMoreOpen(false)}
                className="rounded-md p-2 hover:bg-stein/10"
              >
                <X className="size-5" aria-hidden="true" />
              </button>
            </div>
            <nav aria-label="Weitere Navigation" className="flex flex-col gap-4">
              {NAV_GROUPS.map((group) => (
                <div key={group.labelKey} className="flex flex-col gap-0.5">
                  <h3 className="px-3 pb-1 text-xs font-medium uppercase tracking-wide text-stein-text">
                    <Trans id={group.labelKey} />
                  </h3>
                  {group.items.map((item) => (
                    <NavLink key={item.to} item={item} onNavigate={() => setMoreOpen(false)} />
                  ))}
                </div>
              ))}
            </nav>
          </div>
        </>
      ) : null}
      <nav
        aria-label="Hauptnavigation"
        className="fixed inset-x-0 bottom-0 z-50 flex h-bottom-bar border-t border-stein/15 bg-papier/95 pb-safe-b pl-safe-l pr-safe-r backdrop-blur dark:bg-nacht-2/95 md:hidden"
      >
        {MOBILE_PRIMARY.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.to}
              to={item.to}
              activeOptions={item.to === "/" ? { exact: true } : undefined}
              className={tab}
              activeProps={{ className: `${tab} ${tabActive}` }}
            >
              <Icon className="size-5" strokeWidth={1.75} aria-hidden="true" />
              <Trans id={item.labelKey} />
            </Link>
          );
        })}
        <button
          type="button"
          aria-expanded={moreOpen}
          aria-controls="more-panel"
          onClick={() => setMoreOpen((v) => !v)}
          className={`${tab} ${moreOpen ? tabActive : ""}`}
        >
          {moreOpen ? (
            <ChevronUp className="size-5" aria-hidden="true" />
          ) : (
            <Menu className="size-5" aria-hidden="true" />
          )}
          <Trans id="nav.more" />
        </button>
      </nav>
    </>
  );
}
