// Web mirror of the backend soft value-decay (KONZEPT §5.9, app/modules/tasks/decay.py): an overdue
// task is worth less (-10% per whole day overdue, floored at 50%). Used only to PREVIEW the current
// worth of an open overdue task; the authoritative award is computed server-side at completion.
// Keep these constants in sync with the backend.
export const DECAY_PER_DAY = 0.1;
export const FLOOR = 0.5;

const DAY_MS = 24 * 60 * 60 * 1000;

export function effectivePoints(base: number, dueAt: string | null, now: Date = new Date()): number {
  if (base <= 0 || dueAt === null) return base;
  const due = new Date(dueAt).getTime();
  const daysOverdue = Math.floor((now.getTime() - due) / DAY_MS);
  if (daysOverdue <= 0) return base;
  const multiplier = Math.max(FLOOR, 1 - DECAY_PER_DAY * daysOverdue);
  return Math.round(base * multiplier);
}

export function isOverdue(dueAt: string | null, now: Date = new Date()): boolean {
  return dueAt !== null && new Date(dueAt).getTime() < now.getTime();
}
