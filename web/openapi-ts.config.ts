import { defineConfig } from "@hey-api/openapi-ts";

// Single generator run: types + fetch client + zod schemas from the backend
// OpenAPI (ARCHITECTURE §5, Audit B-08). Run via `npm run openapi` after
// `make openapi` (backend) has written ../backend/openapi.json.
// The output (src/api) is committed; CI's oasdiff + regen-diff gate keeps it in sync.
export default defineConfig({
  input: "../backend/openapi.json",
  output: "src/api",
  plugins: ["@hey-api/client-fetch", "zod"],
});
