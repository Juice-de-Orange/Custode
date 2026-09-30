import { Trans } from "@lingui/react";
import { Link, Outlet, useLocation } from "@tanstack/react-router";
import { useState } from "react";

import { useActiveBanners } from "../banners/queries";
import { useSession } from "../auth/session";
import { AppBottomBar, AppSidebar } from "../components/app-nav";
import { BrandMark } from "../components/brand-mark";
import { CommandPalette } from "../components/command-palette";
import { NoHouseholdState } from "../components/no-household";
import { OfflineDot } from "../components/offline-dot";
import { PwaUpdateToast } from "../components/pwa-update-toast";
import { ThemeToggle } from "../components/theme-toggle";
import { useRealtime } from "../realtime/useRealtime";

// Routes that work without an active household: account (create/join/switch lives
// there), personal settings, and the public legal/release pages. Every other module
// screen is household-scoped and would only produce 403s.
// Public repository of this AGPL-3.0 application (§13 source offer, linked in the footer).
const SOURCE_URL = "https://github.com/Juice-de-Orange/Custode";

const NO_HOUSEHOLD_OK = new Set([
  "/",
  "/profile",
  "/security",
  "/neuigkeiten",
  "/datenschutz",
  "/impressum",
]);

export function RootLayout() {
  useRealtime(); // live query invalidation via SSE while signed in (no-op when signed out)
  const { data: session } = useSession();
  const banners = useActiveBanners(!!session);
  const signedIn = !!session;
  const pathname = useLocation({ select: (l) => l.pathname });
  // Signed in but no active household (fresh account, or multi-household before the
  // pick): show a quiet pointer to the account page instead of a wall of 403 errors.
  const needsHousehold =
    signedIn && session?.household_id == null && !NO_HOUSEHOLD_OK.has(pathname);
  const [cmdkOpen, setCmdkOpen] = useState(false);
  return (
    <div className="min-h-screen bg-kalk text-tinte dark:bg-nacht dark:text-kalk">
      {/* Global operator banners (maintenance notices) — quiet bar above everything, P8-S8b. */}
      {(banners.data?.length ?? 0) > 0 ? (
        <div aria-label="Hinweise" role="region">
          {banners.data?.map((b) => (
            <div
              key={b.id}
              role="status"
              className={`px-4 py-2 text-sm md:px-6 ${
                b.level === "warning" ? "bg-bernstein/15 text-tinte" : "bg-laurus/10 text-tinte"
              } dark:text-kalk`}
            >
              {b.message}
            </div>
          ))}
        </div>
      ) : null}

      {/* Top bar: brand. On desktop it is only shown signed-out (the sidebar carries the brand when
          signed in); signed-out it spans all sizes since there is no sidebar. */}
      <header
        className={`sticky top-0 z-20 flex items-center justify-between gap-4 border-b border-stein/15 bg-kalk/90 px-4 py-3 backdrop-blur dark:bg-nacht/90 ${
          signedIn ? "md:hidden" : ""
        }`}
      >
        <Link to={signedIn ? "/today" : "/"} className="text-tinte dark:text-kalk">
          <BrandMark />
        </Link>
        <ThemeToggle />
      </header>

      {/* Desktop: fixed grouped sidebar; main is offset by its width. */}
      {signedIn ? <AppSidebar onSearch={() => setCmdkOpen(true)} /> : null}
      <div className={signedIn ? "md:pl-60" : ""}>
        <main className="mx-auto w-full max-w-3xl px-4 py-8 pb-content-bottom md:px-8 md:py-10 md:pb-10">
          {needsHousehold ? <NoHouseholdState /> : <Outlet />}
        </main>
        <footer className="border-t border-stein/15 px-4 py-4 text-xs text-stein-text md:px-8">
          <nav aria-label="Rechtliches" className="mx-auto flex max-w-3xl gap-4">
            <Link to="/neuigkeiten" className="hover:underline">
              <Trans id="releases.title" />
            </Link>
            <Link to="/datenschutz" className="hover:underline">
              <Trans id="legal.privacy.title" />
            </Link>
            <Link to="/impressum" className="hover:underline">
              <Trans id="legal.imprint.title" />
            </Link>
            {/* AGPL-3.0 §13: anyone using the app over the network must be able to reach the
                Corresponding Source — a visible link on every page satisfies that. */}
            <a
              href={SOURCE_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              <Trans id="legal.source.title" />
            </a>
          </nav>
        </footer>
      </div>

      {/* Mobile: bottom-tab bar with „Mehr" disclosure. */}
      {signedIn ? <AppBottomBar /> : null}

      {/* ⌘/Ctrl+K command palette (jump to any module + quick actions) + mobile floating trigger. */}
      {signedIn ? <CommandPalette open={cmdkOpen} onOpenChange={setCmdkOpen} /> : null}

      {/* PWA (ADR-0078): SW registration + quiet "new version" toast — also when signed out,
          so the login page installs/updates too. */}
      <PwaUpdateToast />
      <OfflineDot />
    </div>
  );
}
