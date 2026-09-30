import { expect, test } from "vitest";

import { HOUSEHOLDS_QUERY_KEY, ME_QUERY_KEY } from "../auth/session";
import {
  BALANCE_QUERY_KEY,
  CHALLENGE_QUERY_KEY,
  FAIRNESS_QUERY_KEY,
} from "../economy/queries";
import { CALENDAR_QUERY_KEY } from "../calendar/queries";
import { MEALPLAN_QUERY_KEY } from "../mealplan/queries";
import { NOTES_QUERY_KEY } from "../notes/queries";
import { LETTERS_QUERY_KEY } from "../messaging/queries";
import { GUIDES_QUERY_KEY } from "../guides/queries";
import { COMMENTS_QUERY_KEY } from "../comments/queries";
import { LINKS_QUERY_KEY } from "../links/queries";
import { VAULT_QUERY_KEY } from "../vault/queries";
import { CAPTURE_QUERY_KEY } from "../capture/queries";
import { queryKeysForEntity } from "../realtime/invalidation-map";
import { TASKS_QUERY_KEY } from "../tasks/queries";

test("members maps to the /me and households query keys", () => {
  expect(queryKeysForEntity("members")).toEqual([ME_QUERY_KEY, HOUSEHOLDS_QUERY_KEY]);
});

test("tasks maps to the tasks list, balance, challenge + fairness keys", () => {
  expect(queryKeysForEntity("tasks")).toEqual([
    TASKS_QUERY_KEY,
    BALANCE_QUERY_KEY,
    CHALLENGE_QUERY_KEY,
    FAIRNESS_QUERY_KEY,
  ]);
});

test("economy maps to the balance, challenge + fairness keys", () => {
  expect(queryKeysForEntity("economy")).toEqual([
    BALANCE_QUERY_KEY,
    CHALLENGE_QUERY_KEY,
    FAIRNESS_QUERY_KEY,
  ]);
});

test("capture maps to the capture inbox key", () => {
  expect(queryKeysForEntity("capture")).toEqual([CAPTURE_QUERY_KEY]);
});

test("calendar maps to the calendar agenda key", () => {
  expect(queryKeysForEntity("calendar")).toEqual([CALENDAR_QUERY_KEY]);
});

test("mealplan maps to the mealplan week key", () => {
  expect(queryKeysForEntity("mealplan")).toEqual([MEALPLAN_QUERY_KEY]);
});

test("notes maps to the notes list key", () => {
  expect(queryKeysForEntity("notes")).toEqual([NOTES_QUERY_KEY]);
});

test("letters maps to the letters inbox key", () => {
  expect(queryKeysForEntity("letters")).toEqual([LETTERS_QUERY_KEY]);
});

test("guides maps to the guides list key", () => {
  expect(queryKeysForEntity("guides")).toEqual([GUIDES_QUERY_KEY]);
});

test("comments maps to the comments key", () => {
  expect(queryKeysForEntity("comments")).toEqual([COMMENTS_QUERY_KEY]);
});

test("links maps to the links key", () => {
  expect(queryKeysForEntity("links")).toEqual([LINKS_QUERY_KEY]);
});

test("vault maps to the vault key", () => {
  expect(queryKeysForEntity("vault")).toEqual([VAULT_QUERY_KEY]);
});

test("an unknown entity maps to no keys", () => {
  expect(queryKeysForEntity("recipes")).toEqual([]);
});
