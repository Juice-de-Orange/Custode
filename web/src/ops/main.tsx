import { I18nProvider } from "@lingui/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { i18n } from "../i18n/ops";
import { BRAND_NAME } from "../lib/brand";
import { initThemeWatch } from "../lib/theme";
import { queryClient } from "../query";
import "../styles/index.css";
import { configureOpsClient } from "./client";
import { opsRouter } from "./router";

// Separate bundle/entry for the operator console (ARCHITECTURE §8.6: own subdomain, bearer
// auth, no member cookies in scope). Shares the design system, i18n catalog and Query client
// with the member app, but its own router and (bearer) API client.
configureOpsClient();
initThemeWatch();
document.title = `${BRAND_NAME} · Ops`;

const rootEl = document.getElementById("root");
if (!rootEl) {
  throw new Error("Root element #root not found");
}

createRoot(rootEl).render(
  <StrictMode>
    <I18nProvider i18n={i18n}>
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={opsRouter} />
      </QueryClientProvider>
    </I18nProvider>
  </StrictMode>,
);
