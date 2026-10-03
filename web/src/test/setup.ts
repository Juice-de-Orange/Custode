import "fake-indexeddb/auto";
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, expect } from "vitest";
import * as axeMatchers from "vitest-axe/matchers";
import type { AxeMatchers } from "vitest-axe/matchers";

// The suite asserts German copy. jsdom reports an English browser, and the app follows the
// browser language (lib/locale) — so the tests run in a German one. Before any module loads its
// catalog; skipped in the node environment, where nothing renders.
if (typeof window !== "undefined") {
  Object.defineProperty(window.navigator, "languages", { value: ["de-DE", "de"], configurable: true });
  Object.defineProperty(window.navigator, "language", { value: "de-DE", configurable: true });
}

// Runtime accessibility assertions (P8-S9): `expect(await axe(container)).toHaveNoViolations()`.
expect.extend(axeMatchers);

declare module "vitest" {
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type -- matcher augmentation
  interface Assertion extends AxeMatchers {}
  // eslint-disable-next-line @typescript-eslint/no-empty-object-type -- matcher augmentation
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}

// Unmount rendered trees after each test (vitest config has no `globals`, so RTL's
// automatic cleanup is not registered).
afterEach(() => {
  cleanup();
});
