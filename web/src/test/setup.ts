import "fake-indexeddb/auto";

import { cleanup } from "@testing-library/react";
import * as jestDomMatchers from "@testing-library/jest-dom/matchers";
import type { TestingLibraryMatchers } from "@testing-library/jest-dom/matchers";
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

// DOM matchers (toBeInTheDocument, …). Registered by hand instead of via
// "@testing-library/jest-dom/vitest": its type augmentation declares `Assertion<T>`, which
// clashes with Vitest 5's `Assertion<R, T>` (TS2428).
expect.extend(jestDomMatchers);
// Runtime accessibility assertions (P8-S9): `expect(await axe(container)).toHaveNoViolations()`.
expect.extend(axeMatchers);

declare module "vitest" {
  interface Assertion<R extends void | Promise<void> = void>
    extends AxeMatchers, TestingLibraryMatchers<unknown, R> {}
  interface AsymmetricMatchersContaining
    extends AxeMatchers, TestingLibraryMatchers<unknown, unknown> {}
}

// Unmount rendered trees after each test (vitest config has no `globals`, so RTL's
// automatic cleanup is not registered).
afterEach(() => {
  cleanup();
});
