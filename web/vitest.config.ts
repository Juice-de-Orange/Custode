import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // The virtual module only exists inside the Vite build (vite-plugin-pwa); any test that
      // transitively imports the wired PwaUpdateToast resolves this stub instead.
      "virtual:pwa-register/react": fileURLToPath(
        new URL("./src/test/pwa-register-stub.ts", import.meta.url),
      ),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
