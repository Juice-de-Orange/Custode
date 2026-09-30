import { expect, test } from "vitest";

import { i18n } from "../i18n";
import { ProblemError } from "../lib/problem";
import {
  callbackMessage,
  connectionStatusId,
  wearableProblemMessage,
} from "../wearables/errors";

test("known slugs map to their own message", () => {
  expect(wearableProblemMessage(new ProblemError("connection_exists")).id).toBe(
    "wearables.err.exists",
  );
  expect(wearableProblemMessage(new ProblemError("crypto_unconfigured")).id).toBe(
    "wearables.err.cryptoOff",
  );
});

test("an unknown slug still gets a human message, never a raw code", () => {
  expect(wearableProblemMessage(new ProblemError("brand_new")).id).toBe("wearables.err.generic");
  expect(wearableProblemMessage(new Error("boom")).id).toBe("wearables.err.generic");
});

test("callback codes map to their own message", () => {
  expect(callbackMessage("denied").id).toBe("wearables.cb.denied");
  expect(callbackMessage("state_invalid").id).toBe("wearables.cb.stateInvalid");
  expect(callbackMessage("nonsense").id).toBe("wearables.cb.failed");
});

test("needs_reauth outranks a stale last_error", () => {
  expect(connectionStatusId("needs_reauth", "refresh_failed")).toBe(
    "wearables.status.needsReauth",
  );
  expect(connectionStatusId("active", "unreachable")).toBe("wearables.status.problem");
  expect(connectionStatusId("active", null)).toBe("wearables.status.ok");
});

test("every id this module can emit exists in the catalogue", () => {
  const ids = [
    ...["connection_exists", "crypto_unconfigured", "wearables_disabled", "unknown"].map(
      (s) => wearableProblemMessage(new ProblemError(s)).id,
    ),
    ...["denied", "state_invalid", "exchange_failed", "forbidden", "nonsense"].map(
      (c) => callbackMessage(c).id,
    ),
    connectionStatusId("needs_reauth", null),
    connectionStatusId("active", "x"),
    connectionStatusId("active", null),
  ];
  // i18n._ falls back to the id itself when a key is missing — a raw slug in the UI is exactly
  // what this guards against.
  for (const id of ids) expect(i18n._(id)).not.toBe(id);
});
