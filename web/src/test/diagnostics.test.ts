import { beforeEach, describe, expect, it } from "vitest";

import { clearDiagnostics, getDiagnostics, recordDiagnostic } from "../lib/diagnostics";

describe("diagnostics ring buffer", () => {
  beforeEach(() => clearDiagnostics());

  it("records only technical breadcrumb fields (no content) and stamps a timestamp", () => {
    recordDiagnostic({ route: "/recipes", error_ref: "CUS-7Q2F-9K", status: 500 });
    const snap = getDiagnostics();
    expect(snap.entries).toHaveLength(1);
    const e = snap.entries![0];
    expect(e.route).toBe("/recipes");
    expect(e.error_ref).toBe("CUS-7Q2F-9K");
    expect(e.status).toBe(500);
    expect(typeof e.at).toBe("string");
    // Only the known keys exist — no place to smuggle content.
    expect(Object.keys(e).sort()).toEqual(["at", "error_ref", "route", "status"]);
  });

  it("caps the buffer at 25 entries, keeping the most recent", () => {
    for (let i = 0; i < 40; i++) recordDiagnostic({ route: `/r${i}` });
    const snap = getDiagnostics();
    expect(snap.entries).toHaveLength(25);
    expect(snap.entries![24].route).toBe("/r39");
    expect(snap.entries![0].route).toBe("/r15");
  });

  it("always reports an app version", () => {
    expect(getDiagnostics().app_version).toBeTruthy();
  });
});
