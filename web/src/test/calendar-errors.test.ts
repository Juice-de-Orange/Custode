import { describe, expect, test } from "vitest";

import { calendarProblemMessage, syncErrorId } from "../calendar/errors";
import { ProblemError, toProblem } from "../lib/problem";

describe("toProblem extra", () => {
  test("collects flat extra members (backend merges extra into the body)", () => {
    const err = toProblem(
      {
        type: "https://github.com/Juice-de-Orange/Custode/blob/main/docs/errors.md#caldav_write_failed",
        title: "Externer Kalender nicht erreichbar",
        status: 502,
        category: "auth_failed",
      },
      502,
    );
    expect(err.slug).toBe("caldav_write_failed");
    expect(err.extra.category).toBe("auth_failed");
    expect(err.extra.type).toBeUndefined(); // known members never leak into extra
  });

  test("keeps working without extra members", () => {
    const err = toProblem({ type: ".../not_found", title: "x" }, 404);
    expect(err.slug).toBe("not_found");
    expect(err.extra).toEqual({});
  });
});

describe("calendarProblemMessage", () => {
  test("maps write-back slugs", () => {
    expect(calendarProblemMessage(new ProblemError("external_conflict"))).toEqual({
      id: "calendar.err.externalConflict",
    });
    expect(calendarProblemMessage(new ProblemError("caldav_disabled"))).toEqual({
      id: "calendar.subs.sync.sync_disabled",
    });
    expect(calendarProblemMessage(new ProblemError("subscription_exists"))).toEqual({
      id: "calendar.subs.err.exists",
    });
  });

  test("interpolates the readonly field name", () => {
    const err = new ProblemError("external_field_readonly", undefined, undefined, {
      field: "layer",
    });
    expect(calendarProblemMessage(err)).toEqual({
      id: "calendar.err.fieldReadonly",
      values: { field: "layer" },
    });
  });

  test("resolves the write-failed category through the sync texts", () => {
    const err = new ProblemError("caldav_write_failed", undefined, undefined, {
      category: "auth_failed",
    });
    const msg = calendarProblemMessage(err);
    expect(msg.id).toBe("calendar.err.writeFailed");
    // The category value is the already-localised sync text (German catalog active in tests).
    expect(msg.values?.category).toContain("Anmeldung fehlgeschlagen");
  });

  test("falls back for unknown slugs and non-problems", () => {
    expect(calendarProblemMessage(new ProblemError("weird"))).toEqual({ id: "state.error" });
    expect(calendarProblemMessage(new Error("boom"))).toEqual({ id: "state.error" });
  });
});

describe("syncErrorId", () => {
  test("known categories map to their text, unknown to the generic one", () => {
    expect(syncErrorId("unreachable")).toBe("calendar.subs.sync.unreachable");
    expect(syncErrorId("something_new")).toBe("calendar.subs.sync.failed");
  });
});
