import { createRootRoute, createRoute, createRouter, lazyRouteComponent } from "@tanstack/react-router";

import { LoadingState } from "./components/states";
// Eager: the shell + the signed-out surface (this is the first paint, incl. the Lighthouse route `/`).
import { AccountPage } from "./routes/account";
import { LoginPage } from "./routes/login";
import { RegisterPage } from "./routes/register";
import { RootLayout } from "./routes/root";

// Everything else is code-split (lazyRouteComponent): its chunk loads on navigation, so the signed-out
// initial bundle stays small (less parse/execute → better mobile performance; bundle-size gate holds
// the budget). The router shows LoadingState while a route chunk streams in. The named export is
// passed as the second arg (the literal name lets TS narrow to that export).
const rootRoute = createRootRoute({ component: RootLayout });

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: AccountPage });
const loginRoute = createRoute({ getParentRoute: () => rootRoute, path: "/login", component: LoginPage });
const registerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/register",
  component: RegisterPage,
});

const todayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/today",
  component: lazyRouteComponent(() => import("./routes/today"), "TodayPage"),
});

const securityRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/security",
  component: lazyRouteComponent(() => import("./routes/security"), "SecurityPage"),
});

const forgotPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/forgot-password",
  component: lazyRouteComponent(() => import("./routes/forgot-password"), "ForgotPasswordPage"),
});

const resetPasswordRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/reset-password",
  component: lazyRouteComponent(() => import("./routes/reset-password"), "ResetPasswordPage"),
});

const verifyEmailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/verify-email",
  component: lazyRouteComponent(() => import("./routes/verify-email"), "VerifyEmailPage"),
});

const profileRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/profile",
  component: lazyRouteComponent(() => import("./routes/profile"), "ProfilePage"),
});

const childLoginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/child-login",
  component: lazyRouteComponent(() => import("./routes/child-login"), "ChildLoginPage"),
});

const recipesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes",
  component: lazyRouteComponent(() => import("./routes/recipes"), "RecipesPage"),
});

const recipeNewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes/new",
  component: lazyRouteComponent(() => import("./routes/recipe-new"), "RecipeNewPage"),
});

const recipeImportRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes/import",
  component: lazyRouteComponent(() => import("./routes/recipe-import"), "RecipeImportPage"),
});

const recipeDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes/$id",
  component: lazyRouteComponent(() => import("./routes/recipe-detail"), "RecipeDetailPage"),
});

const recipeCookRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/recipes/$id/cook",
  component: lazyRouteComponent(() => import("./routes/recipe-cook"), "RecipeCookPage"),
});

const shoppingRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/shopping",
  component: lazyRouteComponent(() => import("./routes/shopping"), "ShoppingPage"),
});

const tasksRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/tasks",
  component: lazyRouteComponent(() => import("./routes/tasks"), "TasksPage"),
});

const rewardsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/rewards",
  component: lazyRouteComponent(() => import("./routes/rewards"), "RewardsPage"),
});

const challengeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/challenge",
  component: lazyRouteComponent(() => import("./routes/challenge"), "ChallengePage"),
});

const roomsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/rooms",
  component: lazyRouteComponent(() => import("./routes/rooms"), "RoomsPage"),
});

const marketplaceRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/marketplace",
  component: lazyRouteComponent(() => import("./routes/marketplace"), "MarketplacePage"),
});

const captureRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/capture",
  component: lazyRouteComponent(() => import("./routes/capture"), "CapturePage"),
});

const calendarRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/calendar",
  component: lazyRouteComponent(() => import("./routes/calendar"), "CalendarPage"),
});

const mealplanRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/mealplan",
  component: lazyRouteComponent(() => import("./routes/mealplan"), "MealplanPage"),
});

const notesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/notes",
  component: lazyRouteComponent(() => import("./routes/notes"), "NotesPage"),
});

const lettersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/letters",
  component: lazyRouteComponent(() => import("./routes/letters"), "LettersPage"),
});

const guidesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/guides",
  component: lazyRouteComponent(() => import("./routes/guides"), "GuidesPage"),
});

const vaultRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/vault",
  component: lazyRouteComponent(() => import("./routes/vault"), "VaultPage"),
});

const feedbackRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/feedback",
  component: lazyRouteComponent(() => import("./routes/feedback"), "FeedbackPage"),
});

const privacyRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/datenschutz",
  component: lazyRouteComponent(() => import("./routes/legal"), "PrivacyPage"),
});

const imprintRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/impressum",
  component: lazyRouteComponent(() => import("./routes/legal"), "ImprintPage"),
});

const releasesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/neuigkeiten",
  component: lazyRouteComponent(() => import("./routes/releases"), "ReleasesPage"),
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  loginRoute,
  registerRoute,
  todayRoute,
  securityRoute,
  forgotPasswordRoute,
  resetPasswordRoute,
  verifyEmailRoute,
  profileRoute,
  childLoginRoute,
  recipesRoute,
  recipeNewRoute,
  recipeImportRoute,
  recipeDetailRoute,
  recipeCookRoute,
  shoppingRoute,
  tasksRoute,
  rewardsRoute,
  challengeRoute,
  roomsRoute,
  marketplaceRoute,
  captureRoute,
  calendarRoute,
  mealplanRoute,
  notesRoute,
  lettersRoute,
  guidesRoute,
  vaultRoute,
  feedbackRoute,
  privacyRoute,
  imprintRoute,
  releasesRoute,
]);

export const router = createRouter({
  routeTree,
  defaultPendingComponent: () => (
    <main className="mx-auto w-full max-w-3xl px-4 py-8 md:px-8 md:py-10">
      <LoadingState />
    </main>
  ),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
