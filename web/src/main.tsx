import { I18nProvider } from "@lingui/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { configureAuthClient } from "./auth/client";
import { i18n } from "./i18n";
import { BRAND_NAME } from "./lib/brand";
import { initThemeWatch } from "./lib/theme";
import { queryClient } from "./query";
import { router } from "./router";
import "./styles/index.css";

configureAuthClient();
initThemeWatch(); // keep a "system" theme preference reactive to OS changes (pre-paint sets the class)
document.title = BRAND_NAME;

// A deploy can drop old hashed chunks while a stale tab lazy-loads a route. The service
// worker's prompt-update keeps serving the old precache, but a plain browser tab can still
// race a deploy. Reload recovers; the 60 s cooldown prevents a reload loop while still
// self-healing a long-lived tab that spans SEVERAL deploys. Storage access is guarded like in
// the pre-paint theme script (private-mode/sandbox may deny it).
window.addEventListener("vite:preloadError", (event) => {
  try {
    const last = Number(sessionStorage.getItem("custode-chunk-reload") ?? 0);
    if (Date.now() - last < 60_000) return; // rapid repeat → a real failure, surface it
    sessionStorage.setItem("custode-chunk-reload", String(Date.now()));
  } catch {
    return; // no storage → no loop protection → don't auto-reload
  }
  event.preventDefault();
  window.location.reload();
});

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

createRoot(rootEl).render(
  <StrictMode>
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    </I18nProvider>
  </StrictMode>,
);
