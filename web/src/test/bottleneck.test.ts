import { expect, test } from "vitest";

import { BOTTLENECK_THRESHOLD, countMyOverdue, hasBottleneck } from "../tasks/bottleneck";

const NOW = new Date("2026-06-24T12:00:00Z");
const PAST = "2026-06-20T12:00:00Z";
const FUTURE = "2026-06-30T12:00:00Z";

function inst(over: Partial<{ status: string; assigned_to: string | null; due_at: string | null }>) {
  return { status: "open", assigned_to: "me", due_at: PAST, ...over };
}

test("counts only my own open overdue tasks", () => {
  const items = [
    inst({}), // mine, open, overdue -> counts
    inst({ due_at: FUTURE }), // not overdue
    inst({ status: "done" }), // already done
    inst({ assigned_to: "other" }), // someone else's
    inst({ due_at: null }), // no due date
  ];
  expect(countMyOverdue(items, "me", NOW)).toBe(1);
});

test("hasBottleneck triggers at the threshold", () => {
  expect(hasBottleneck(BOTTLENECK_THRESHOLD - 1)).toBe(false);
  expect(hasBottleneck(BOTTLENECK_THRESHOLD)).toBe(true);
});
