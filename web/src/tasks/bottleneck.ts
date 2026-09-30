// "Bottleneck" heuristic (KONZEPT Synergie S-10): when a member is sitting on several of their own
// overdue tasks, nudge them to offer some on the marketplace. Pure so it is unit-tested in isolation.
export const BOTTLENECK_THRESHOLD = 3;

type OverdueCandidate = {
  status: string;
  assigned_to: string | null;
  due_at: string | null;
};

export function countMyOverdue(
  instances: ReadonlyArray<OverdueCandidate>,
  myId: string,
  now: Date = new Date(),
): number {
  return instances.filter(
    (i) =>
      i.status === "open" &&
      i.assigned_to === myId &&
      i.due_at !== null &&
      new Date(i.due_at) < now,
  ).length;
}

export function hasBottleneck(overdueCount: number, threshold = BOTTLENECK_THRESHOLD): boolean {
  return overdueCount >= threshold;
}
