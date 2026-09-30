import { Trans } from "@lingui/react";

import { DashboardTile } from "../../components/dashboard-tile";
import { BannerForm } from "../components/banner-form";
import { useCreateBanner, useDeactivateBanner, useOpsBanners } from "../queries";

// Audited banner management: create a global banner and deactivate active ones. Both writes are
// recorded in the append-only audit_log server-side (ADR-0073) and run as ops_actions.
export function OpsBanners() {
  const banners = useOpsBanners();
  const create = useCreateBanner();
  const deactivate = useDeactivateBanner();

  return (
    <section aria-labelledby="ops-banners-heading" className="space-y-4">
      <h1 id="ops-banners-heading" className="font-display text-2xl">
        <Trans id="ops.banners.title" />
      </h1>

      <DashboardTile title={<Trans id="ops.banners.new" />} isLoading={false} isError={false} isEmpty={false}>
        <BannerForm onSubmit={(values) => create.mutate(values)} pending={create.isPending} />
      </DashboardTile>

      <DashboardTile
        title={<Trans id="ops.banners.list" />}
        isLoading={banners.isLoading}
        isError={banners.isError}
        isEmpty={(banners.data?.length ?? 0) === 0}
        emptyText={<Trans id="ops.banners.empty" />}
      >
        <ul className="space-y-2">
          {banners.data?.map((b) => (
            <li
              key={b.id}
              className="flex items-center justify-between gap-3 rounded-md border border-stein/20 p-3"
            >
              <div>
                <span className="mr-2 rounded bg-stein/15 px-1.5 py-0.5 text-xs uppercase text-stein-text">
                  {b.level}
                </span>
                <span>{b.message}</span>
                {!b.is_active ? (
                  <span className="ml-2 text-xs text-stein-text">
                    (<Trans id="ops.banners.inactive" />)
                  </span>
                ) : null}
              </div>
              {b.is_active ? (
                <button
                  type="button"
                  onClick={() => deactivate.mutate(b.id)}
                  disabled={deactivate.isPending}
                  className="shrink-0 rounded-md border border-stein/40 px-3 py-1 text-sm hover:bg-stein/10 dark:hover:bg-kalk/10 focus:outline-none focus:ring-2 focus:ring-laurus/40 dark:focus:ring-laurus-dark/40 disabled:opacity-60"
                >
                  <Trans id="ops.banners.deactivate" />
                </button>
              ) : null}
            </li>
          ))}
        </ul>
      </DashboardTile>
    </section>
  );
}
