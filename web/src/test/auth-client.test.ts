import { expect, test, vi } from "vitest";

import { handleResponse } from "../auth/client";

const res = (status: number) => new Response(null, { status });
const req = (url: string, method = "GET") => new Request(url, { method });

test("passes non-401 responses through without refreshing", async () => {
  const refresh = vi.fn();
  const replay = vi.fn();
  const out = await handleResponse(res(200), req("https://app/v1/auth/me"), { refresh, replay });
  expect(out.status).toBe(200);
  expect(refresh).not.toHaveBeenCalled();
});

test("does not refresh on 401 from auth bootstrap routes", async () => {
  const refresh = vi.fn();
  const replay = vi.fn();
  const out = await handleResponse(res(401), req("https://app/v1/auth/login", "POST"), {
    refresh,
    replay,
  });
  expect(out.status).toBe(401);
  expect(refresh).not.toHaveBeenCalled();
});

test("refreshes once and replays on 401 from an authed route", async () => {
  const refresh = vi.fn().mockResolvedValue(true);
  const replay = vi.fn().mockResolvedValue(res(200));
  const out = await handleResponse(res(401), req("https://app/v1/auth/me"), { refresh, replay });
  expect(refresh).toHaveBeenCalledOnce();
  expect(replay).toHaveBeenCalledOnce();
  expect(out.status).toBe(200);
});

test("surfaces the original 401 when the refresh fails", async () => {
  const refresh = vi.fn().mockResolvedValue(false);
  const replay = vi.fn();
  const out = await handleResponse(res(401), req("https://app/v1/auth/me"), { refresh, replay });
  expect(refresh).toHaveBeenCalledOnce();
  expect(replay).not.toHaveBeenCalled();
  expect(out.status).toBe(401);
});

// --- der Fall, den der alte Test nie gebaut hat -------------------------------------------------
//
// `req()` oben erzeugt niemals einen Body — auch der "POST"-Fall ist bodylos. Damit lief der
// Clone-Pfad ausschliesslich gegen einen frischen, unverbrauchten Request, wo `clone()` trivial
// gelingt. Der Produktionsfall (ein von `fetch` bereits geleerter POST-Body) war null abgedeckt,
// und deshalb sah der Kommentar "a consumed POST body throws -> caught" wie eine Entscheidung aus
// statt wie ein Ausfall bei jeder Schreibaktion nach einer Pause.

/** Ein Request, dessen Body `fetch` bereits verbraucht hat — der Zustand, den der
 *  Response-Interceptor in Produktion wirklich sieht. `clone()` darauf wirft. */
async function spentRequest(url: string, method = "POST"): Promise<Request> {
  const request = new Request(url, { method, body: JSON.stringify({ a: 1 }) });
  await request.text(); // Stellvertreter fuer `fetch`, das den Stream leert
  return request;
}

test("a write with a consumed body replays from the buffered copy", async () => {
  const request = await spentRequest("https://app/v1/tasks/instances");
  const buffered = new Request("https://app/v1/tasks/instances", {
    method: "POST",
    body: JSON.stringify({ a: 1 }),
  });
  const refresh = vi.fn().mockResolvedValue(true);
  const replay = vi.fn().mockResolvedValue(res(201));

  const out = await handleResponse(res(401), request, {
    refresh,
    replay,
    buffered: () => buffered,
  });

  expect(replay).toHaveBeenCalledOnce();
  expect(out.status).toBe(201);
  await expect((replay.mock.calls[0][0] as Request).text()).resolves.toBe('{"a":1}');
});

test("without a buffered copy a consumed body still degrades to the original 401", async () => {
  const request = await spentRequest("https://app/v1/tasks/instances");
  const refresh = vi.fn().mockResolvedValue(true);
  const replay = vi.fn();

  const out = await handleResponse(res(401), request, { refresh, replay });

  // Genau das war bisher der EINZIGE Pfad fuer Schreib-Requests: `clone()` wirft, der catch gibt
  // die urspruengliche 401 zurueck. Er bleibt als Rueckfallebene richtig — neu ist, dass er nicht
  // mehr der Normalfall ist.
  expect(replay).not.toHaveBeenCalled();
  expect(out.status).toBe(401);
});

test("login-events is an authenticated route and its 401 heals", async () => {
  // `path.includes("/login")` matchte auch `/v1/auth/login-events`: die Sicherheits-Aktivitaet
  // auf /security fiel nach fuenfzehn Minuten stumm aus, weil ihr 401 nie geheilt wurde.
  const refresh = vi.fn().mockResolvedValue(true);
  const replay = vi.fn().mockResolvedValue(res(200));
  const out = await handleResponse(res(401), req("https://app/v1/auth/login-events"), {
    refresh,
    replay,
  });
  expect(refresh).toHaveBeenCalledOnce();
  expect(out.status).toBe(200);
});

test("the passkey login ceremony is still exempt", async () => {
  const refresh = vi.fn();
  const replay = vi.fn();
  const out = await handleResponse(
    res(401),
    req("https://app/v1/auth/passkeys/login/begin", "POST"),
    { refresh, replay },
  );
  expect(out.status).toBe(401);
  expect(refresh).not.toHaveBeenCalled();
});

test("the child PIN login is exempt too — a 401 there means a wrong PIN", async () => {
  const refresh = vi.fn();
  const replay = vi.fn();
  const out = await handleResponse(res(401), req("https://app/v1/auth/child-login", "POST"), {
    refresh,
    replay,
  });
  expect(out.status).toBe(401);
  expect(refresh).not.toHaveBeenCalled();
});
