import { HOUSEHOLDS_QUERY_KEY, ME_QUERY_KEY } from "../auth/session";
import {
  BALANCE_QUERY_KEY,
  CHALLENGE_QUERY_KEY,
  FAIRNESS_QUERY_KEY,
  REDEMPTIONS_QUERY_KEY,
  REWARDS_QUERY_KEY,
} from "../economy/queries";
import { CALENDAR_QUERY_KEY } from "../calendar/queries";
import { CAPTURE_QUERY_KEY } from "../capture/queries";
import { LISTINGS_QUERY_KEY } from "../marketplace/queries";
import { MEALPLAN_QUERY_KEY } from "../mealplan/queries";
import { COMMENTS_QUERY_KEY } from "../comments/queries";
import { FEEDBACK_QUERY_KEY } from "../feedback/queries";
import { GUIDES_QUERY_KEY } from "../guides/queries";
import { LINKS_QUERY_KEY } from "../links/queries";
import { VAULT_QUERY_KEY } from "../vault/queries";
import { LETTERS_QUERY_KEY } from "../messaging/queries";
import { NOTES_QUERY_KEY } from "../notes/queries";
import { SHOPPING_QUERY_KEY } from "../shopping/queries";
import { sync as syncShopping } from "../shopping/sync";
import { TASKS_QUERY_KEY } from "../tasks/queries";

// Which query keys to invalidate when an entity changes in the active household. The web has
// no dedicated members query yet, so a member change refreshes /me + the household list (both
// reflect role/membership). Add rows as queries are introduced.
const KEYS_BY_ENTITY: Record<string, readonly (readonly unknown[])[]> = {
  members: [ME_QUERY_KEY, HOUSEHOLDS_QUERY_KEY],
  shopping: [SHOPPING_QUERY_KEY],
  // A "tasks" hint refreshes the templates + instances lists, the points balance AND the weekly
  // challenge standings (a completion credits the ledger, ADR-0035) — live on other devices.
  tasks: [TASKS_QUERY_KEY, BALANCE_QUERY_KEY, CHALLENGE_QUERY_KEY, FAIRNESS_QUERY_KEY],
  // A "rewards" hint (catalog change or redemption) refreshes the catalog, confirm list + balance.
  rewards: [REWARDS_QUERY_KEY, REDEMPTIONS_QUERY_KEY, BALANCE_QUERY_KEY],
  // A "economy" hint (thank-you sent) refreshes balances + the challenge/fairness views.
  economy: [BALANCE_QUERY_KEY, CHALLENGE_QUERY_KEY, FAIRNESS_QUERY_KEY],
  // A "marketplace" hint (listing created/sold/settled) refreshes listings + balance.
  marketplace: [LISTINGS_QUERY_KEY, BALANCE_QUERY_KEY],
  // A "capture" hint (Zuruf created/processed) refreshes the triage inbox.
  capture: [CAPTURE_QUERY_KEY],
  // A "calendar" hint (event created/updated/deleted) refreshes the agenda.
  calendar: [CALENDAR_QUERY_KEY],
  // A "mealplan" hint (a slot changed) refreshes the week grid — live on other devices.
  mealplan: [MEALPLAN_QUERY_KEY],
  // A "notes" hint (note created/updated/deleted) refreshes the notes list — live on other devices.
  notes: [NOTES_QUERY_KEY],
  // A "letters" hint (letter sent or read) refreshes the inbox + unread badge — live on other devices.
  letters: [LETTERS_QUERY_KEY],
  // A "guides" hint (guide created/updated/deleted) refreshes the guide list/search — live everywhere.
  guides: [GUIDES_QUERY_KEY],
  // A "comments" hint (comment posted/deleted) refreshes the open thread — live on other devices.
  comments: [COMMENTS_QUERY_KEY],
  // A "links" hint (object linked/unlinked) refreshes the open link panel — live on other devices.
  links: [LINKS_QUERY_KEY],
  // A "vault" hint (item or key envelope changed) refreshes the vault list/keys — live elsewhere.
  vault: [VAULT_QUERY_KEY],
  // A "feedback" hint (a submission landed) refreshes the member's own-submissions list.
  feedback: [FEEDBACK_QUERY_KEY],
};

// Entities whose data lives client-side (Dexie) need a fetch before the cache re-reads: a "shopping"
// hint pulls the delta into Dexie first, then invalidation re-renders.
const SIDE_EFFECTS: Record<string, () => Promise<void>> = {
  shopping: syncShopping,
};

export function queryKeysForEntity(entity: string): readonly (readonly unknown[])[] {
  return KEYS_BY_ENTITY[entity] ?? [];
}

export function sideEffectForEntity(entity: string): (() => Promise<void>) | undefined {
  return SIDE_EFFECTS[entity];
}
