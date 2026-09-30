import "fake-indexeddb/auto";
import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach, expect } from "vitest";
import * as axeMatchers from "vitest-axe/matchers";
import type { AxeMatchers } from "vitest-axe/matchers";

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
