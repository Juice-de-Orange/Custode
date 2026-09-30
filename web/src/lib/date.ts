// Shared date helpers for the household calendar week (Monday-based, KONZEPT §5.4) and the
// „Heute" dashboard. Kept framework-free so they are trivially unit-testable.

// The Monday (ISO week start) of the week containing `d`, as a local ISO date string.
export function mondayOf(d: Date): string {
  const copy = new Date(d);
  copy.setDate(copy.getDate() - dayOfWeekMondayZero(copy));
  return localIso(copy);
}

// Weekday with Monday = 0 … Sunday = 6 (the mealplanner's `day_of_week` convention).
export function dayOfWeekMondayZero(d: Date): number {
  return (d.getDay() + 6) % 7;
}

// `d` as a local `YYYY-MM-DD` (not UTC — the household lives in its own wall-clock day).
export function todayIso(d: Date = new Date()): string {
  return localIso(d);
}

// The local day's [start, end) as ISO timestamps, for the calendar's `from`/`to` window.
export function todayRange(d: Date = new Date()): { from: string; to: string } {
  const start = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const end = new Date(start);
  end.setDate(end.getDate() + 1);
  return { from: start.toISOString(), to: end.toISOString() };
}

function localIso(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}
