import { Trans } from "@lingui/react";
import { Outlet, useNavigate } from "@tanstack/react-router";

import { BrandMark } from "../../components/brand-mark";
import { ThemeToggle } from "../../components/theme-toggle";
import { OpsNavLink } from "../components/ops-nav-link";
import { useOpsLogout, useOpsSession } from "../queries";

// Shell for the operator console: brand + console label, the signed-in operator, and logout.
// The header only renders the operator controls once a session exists (login page has none).
export function OpsLayout() {
  const navigate = useNavigate();
  const session = useOpsSession();
  const logout = useOpsLogout();

  const onLogout = () => {
    logout.mutate(undefined, { onSuccess: () => navigate({ to: "/login" }) });
  };

  return (
    <div className="min-h-screen bg-kalk text-tinte dark:bg-nacht dark:text-kalk">
      <header className="flex items-center justify-between border-b border-stein/30 px-4 py-3">
        <span className="flex items-center gap-2">
          <BrandMark />
          <span className="text-stein-text">
            · <Trans id="ops.console" />
          </span>
        </span>
        <div className="flex items-center gap-3 text-sm">
          {session.data ? (
            <>
            <nav aria-label="ops" className="flex items-center gap-3">
              <OpsNavLink to="/">
                <Trans id="ops.dashboard.title" />
              </OpsNavLink>
              <OpsNavLink to="/banners">
                <Trans id="ops.banners.title" />
              </OpsNavLink>
              <OpsNavLink to="/flags">
                <Trans id="ops.flags.title" />
              </OpsNavLink>
              <OpsNavLink to="/households">
                <Trans id="ops.households.title" />
              </OpsNavLink>
              <OpsNavLink to="/feedback">
                <Trans id="ops.feedback.title" />
              </OpsNavLink>
              <OpsNavLink to="/operators">
                <Trans id="ops.operators.title" />
              </OpsNavLink>
              <OpsNavLink to="/passkeys">
                <Trans id="ops.passkeys.title" />
              </OpsNavLink>
              <OpsNavLink to="/audit">
                <Trans id="ops.audit.title" />
              </OpsNavLink>
            </nav>
            <span className="text-stein-text">{session.data.email}</span>
            <button
              type="button"
              onClick={onLogout}
              className="rounded-md border border-stein/40 px-3 py-1 hover:bg-stein/10 dark:hover:bg-kalk/10 focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40"
            >
              <Trans id="ops.logout" />
            </button>
            </>
          ) : null}
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
