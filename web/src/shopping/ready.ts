// "List ready for a trip" heuristic (KONZEPT Synergie S-17): once a list has accumulated enough
// open items, nudge the user to schedule a shopping slot. Pure so it is unit-tested in isolation.
export const TRIP_READY_THRESHOLD = 5;

export function listReadyForTrip(openCount: number, threshold = TRIP_READY_THRESHOLD): boolean {
  return openCount >= threshold;
}

// Handoff key: the shopping nudge stashes an intent the calendar's scheduling panel reads once to
// prefill (title + duration), so the cross-page jump arrives ready to find a slot.
export const PLAN_INTENT_KEY = "custode.plan.intent";
