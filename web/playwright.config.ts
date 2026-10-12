import { defineConfig, devices } from "@playwright/test";

// Browser tests against a RUNNING stack (the built web app behind Caddy + api + database), not a
// dev server: the offline path needs the real service worker, which only the production build
// registers. Start the stack first (README quick start, or the e2e job in .github/workflows/ci.yml),
// then `npm run e2e`. E2E_BASE_URL points elsewhere than the quick start's default port.
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  retries: 0,
  workers: 1,
  reporter: process.env.CI ? [["list"], ["github"]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    locale: "en-US",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
