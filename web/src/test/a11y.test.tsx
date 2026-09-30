import { I18nProvider } from "@lingui/react";
import { render } from "@testing-library/react";
import { Home, ShoppingCart } from "lucide-react";
import { expect, test } from "vitest";
import { axe } from "vitest-axe";

import { Button } from "../components/button";
import { CommandDialog } from "../components/command-palette";
import { DashboardTile } from "../components/dashboard-tile";
import { Field } from "../components/field";
import { EmptyState, ErrorState, LoadingState } from "../components/states";
import { i18n } from "./i18n-both";
import { SignupsView } from "../ops/components/kpi-views";
import { ReleasesPage } from "../routes/releases";
import { ConsentPicker } from "../wearables/wearables-section";

// Runtime accessibility gate for the cross-cutting building blocks (P8-S9). These render on most
// routes (the mandatory Empty/Loading/Error trio, buttons, dashboard tiles), so keeping them
// axe-clean covers the bulk of the app's a11y surface without spinning up every route's providers.
async function expectNoViolations(ui: React.ReactNode) {
  const { container } = render(<I18nProvider i18n={i18n}>{ui}</I18nProvider>);
  expect(await axe(container)).toHaveNoViolations();
}

test("Empty/Loading/Error states have no axe violations", async () => {
  await expectNoViolations(
    <main>
      <LoadingState />
      <EmptyState>Nichts hier</EmptyState>
      <ErrorState />
    </main>,
  );
});

test("Button has no axe violations", async () => {
  await expectNoViolations(<Button onClick={() => {}}>Speichern</Button>);
});

test("SubscriptionCard/SubscriptionEditForm have no axe violations", async () => {
  const { SubscriptionCard, SubscriptionEditForm } = await import(
    "../calendar/subscriptions-section"
  );
  const sub = {
    id: "s1",
    member_id: "me",
    label: "Nextcloud",
    caldav_url: "https://cloud.example.de/dav/",
    enabled: true,
    has_credentials: true,
    last_sync_at: "2026-07-23T06:00:00Z",
    last_sync_error: null,
  };
  await expectNoViolations(
    <main>
      <ul>
        <SubscriptionCard
          sub={sub}
          pending={false}
          onCheck={() => {}}
      onEdit={() => {}}
          onToggle={() => {}}
          onDelete={() => {}}
        />
        <SubscriptionCard
          sub={{ ...sub, id: "s2", enabled: false, last_sync_error: "auth_failed" }}
          pending={false}
          onCheck={() => {}}
      onEdit={() => {}}
          onToggle={() => {}}
          onDelete={() => {}}
        />
        <SubscriptionEditForm
          initial={{ ...sub, id: "s3", etag: '"1"' }}
          pending={false}
          onSubmit={() => {}}
          onCancel={() => {}}
        />
      </ul>
    </main>,
  );
});

test("Button danger variant has no axe violations", async () => {
  await expectNoViolations(
    <Button variant="danger" onClick={() => {}}>
      Löschen
    </Button>,
  );
});

test("DashboardTile (loading/empty/content) has no axe violations", async () => {
  // No `to` prop — that renders a TanStack <Link>, which needs a router we don't set up here.
  await expectNoViolations(
    <main>
      <DashboardTile title="Aufgaben" isLoading isError={false} isEmpty={false}>
        {null}
      </DashboardTile>
      <DashboardTile title="Einkauf" isLoading={false} isError={false} isEmpty emptyText="leer">
        {null}
      </DashboardTile>
      <DashboardTile title="Essen" isLoading={false} isError={false} isEmpty={false}>
        <p>Inhalt</p>
      </DashboardTile>
    </main>,
  );
});

test("Field (labelled input) has no axe violations", async () => {
  await expectNoViolations(
    <main>
      <Field id="a11y-name" label="Name" />
    </main>,
  );
});

test("ErrorState with a reference code has no axe violations", async () => {
  await expectNoViolations(
    <main>
      <ErrorState reference="CUS-7Q2F-9K" />
    </main>,
  );
});

test("ReleasesPage (release notes) has no axe violations", async () => {
  await expectNoViolations(<ReleasesPage />);
});

test("CommandDialog (open, combobox + listbox) has no axe violations", async () => {
  // Radix Dialog portals to <body>, so axe the whole document rather than the render container.
  render(
    <I18nProvider i18n={i18n}>
      <CommandDialog
        open
        onOpenChange={() => {}}
        commands={[
          { id: "a", label: "Heute", hint: "Alltag", icon: Home, run: () => {} },
          { id: "b", label: "Einkauf", hint: "Alltag", icon: ShoppingCart, run: () => {} },
        ]}
      />
    </I18nProvider>,
  );
  expect(await axe(document.body)).toHaveNoViolations();
});

test("CommandDialog (no matches) has no axe violations", async () => {
  render(
    <I18nProvider i18n={i18n}>
      <CommandDialog open onOpenChange={() => {}} commands={[]} />
    </I18nProvider>,
  );
  expect(await axe(document.body)).toHaveNoViolations();
});

test("SignupsView (KPI sparklines + table) has no axe violations", async () => {
  // API order is newest-first; the sparklines read it reversed.
  await expectNoViolations(
    <main>
      <SignupsView
        daily={[
          { day: "2026-07-03", new_households: 2, new_users: 4 },
          { day: "2026-07-02", new_households: 0, new_users: 1 },
          { day: "2026-07-01", new_households: 3, new_users: 3 },
        ]}
      />
    </main>,
  );
});

test("the wearable consent picker has no axe violations", async () => {
  // Checkbox group for Art.-9 data types: every box needs a real label and the group a legend —
  // a consent control that a screen reader cannot read back is not consent.
  await expectNoViolations(
    <main>
      <ConsentPicker idPrefix="a11y" selected={new Set(["wearable_sleep"])} onToggle={() => {}} />
    </main>,
  );
});
