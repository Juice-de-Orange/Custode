import {
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";

import { hasOpsToken } from "./client";
import { OpsAudit } from "./routes/audit";
import { OpsBanners } from "./routes/banners";
import { OpsDashboard } from "./routes/dashboard";
import { OpsFeedback } from "./routes/feedback";
import { OpsFlagsPage } from "./routes/flags";
import { OpsHouseholds } from "./routes/households";
import { OpsLayout } from "./routes/layout";
import { OpsLoginPage } from "./routes/login";
import { OpsOperators } from "./routes/operators";
import { OpsPasskeysPage } from "./routes/passkeys";

const rootRoute = createRootRoute({ component: OpsLayout });

// Guard the console behind a bearer token. The token lives in memory, so a fresh load (no
// token yet) lands on /login; an authenticated operator visiting /login is sent to the home.
const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsDashboard,
});

const loginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/login",
  beforeLoad: () => {
    if (hasOpsToken()) throw redirect({ to: "/" });
  },
  component: OpsLoginPage,
});

const bannersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/banners",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsBanners,
});

const flagsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/flags",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsFlagsPage,
});

const householdsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/households",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsHouseholds,
});

const feedbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/feedback",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsFeedback,
});

const operatorsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/operators",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsOperators,
});

const passkeysRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/passkeys",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsPasskeysPage,
});

const auditRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/audit",
  beforeLoad: () => {
    if (!hasOpsToken()) throw redirect({ to: "/login" });
  },
  component: OpsAudit,
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  loginRoute,
  bannersRoute,
  flagsRoute,
  householdsRoute,
  feedbackRoute,
  operatorsRoute,
  passkeysRoute,
  auditRoute,
]);

// The global ``Register`` augmentation (member router type) is intentionally NOT re-declared
// here: a second declaration would conflict in the shared tsc project. At runtime navigation
// resolves against this router via RouterProvider context; the shared paths (``/``, ``/login``)
// typecheck against the member route tree.
export const opsRouter = createRouter({ routeTree });
