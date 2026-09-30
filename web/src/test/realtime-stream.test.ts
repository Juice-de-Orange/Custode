import { afterEach, expect, test, vi } from "vitest";

import { openInvalidationStream } from "../realtime/stream";

const CONNECTING = 0;
const CLOSED = 2;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners: Record<string, ((event: { data: string }) => void)[]> = {};
  closed = false;
  readyState = CONNECTING;
  constructor(
    readonly url: string,
    readonly init?: { withCredentials?: boolean },
  ) {
    FakeEventSource.instances.push(this);
  }
  addEventListener(type: string, cb: (event: { data: string }) => void) {
    (this.listeners[type] ??= []).push(cb);
  }
  emit(type: string, data = "") {
    for (const cb of this.listeners[type] ?? []) cb({ data });
  }
  /** The browser's behaviour on a non-2xx response: give up for good. */
  failPermanently() {
    this.readyState = CLOSED;
    this.emit("error");
  }
  /** A dropped connection: the browser retries by itself, readyState stays CONNECTING. */
  dropTransiently() {
    this.readyState = CONNECTING;
    this.emit("error");
  }
  close() {
    this.closed = true;
    this.readyState = CLOSED;
  }
}

afterEach(() => {
  FakeEventSource.instances = [];
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test("connects same-origin with credentials and delivers parsed hints", () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const onHint = vi.fn();
  openInvalidationStream(onHint);

  const source = FakeEventSource.instances[0];
  expect(source.url).toBe("/v1/stream");
  expect(source.init?.withCredentials).toBe(true);

  source.emit("invalidate", JSON.stringify({ entity: "members", id: "h1", version: 2 }));
  expect(onHint).toHaveBeenCalledWith({ entity: "members", id: "h1", version: 2 });
});

test("ignores a malformed frame without throwing", () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const onHint = vi.fn();
  openInvalidationStream(onHint);
  FakeEventSource.instances[0].emit("invalidate", "not json {");
  expect(onHint).not.toHaveBeenCalled();
});

test("close() closes the underlying EventSource", () => {
  vi.stubGlobal("EventSource", FakeEventSource);
  const stream = openInvalidationStream(vi.fn());
  stream.close();
  expect(FakeEventSource.instances[0].closed).toBe(true);
});

test("null path: no EventSource -> no-op stream, no throw", () => {
  vi.stubGlobal("EventSource", undefined);
  const onHint = vi.fn();
  const stream = openInvalidationStream(onHint);
  stream.close();
  expect(onHint).not.toHaveBeenCalled();
  expect(FakeEventSource.instances).toHaveLength(0);
});

// --- Der permanente Schluss (11-B2) -------------------------------------------------------------
//
// Der alte Kommentar in stream.ts sagte "the browser auto-reconnects on drop, so there is no
// manual retry loop here". Das gilt fuer einen *Abbruch* — und nicht fuer den Fall, der wirklich
// eintritt: bei einer Nicht-2xx-Antwort gibt der Browser endgueltig auf. Das Access-Cookie laeuft
// nach fuenfzehn Minuten ab, /v1/stream antwortet 401, und der Live-Kanal blieb den Rest der
// Sitzung stumm — EventSource laeuft nicht durch den fetch-Interceptor.

test("a permanent close renews the session and reconnects", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  const renew = vi.fn().mockResolvedValue(true);

  openInvalidationStream(vi.fn(), { renew, retryDelaysMs: [10] });
  expect(FakeEventSource.instances).toHaveLength(1);

  FakeEventSource.instances[0].failPermanently();
  await vi.advanceTimersByTimeAsync(10);

  expect(renew).toHaveBeenCalledTimes(1);
  expect(FakeEventSource.instances).toHaveLength(2);
});

test("a transient drop is left to the browser", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  const renew = vi.fn().mockResolvedValue(true);

  openInvalidationStream(vi.fn(), { renew, retryDelaysMs: [10] });
  FakeEventSource.instances[0].dropTransiently();
  await vi.advanceTimersByTimeAsync(50);

  // Ein zweiter EventSource hier waere ein Wettlauf mit dem Browser, der selbst schon
  // wiederverbindet — zwei offene Kanaele auf denselben Stream.
  expect(renew).not.toHaveBeenCalled();
  expect(FakeEventSource.instances).toHaveLength(1);
});

test("a failing renewal still reconnects, with the next (longer) delay", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  const renew = vi.fn().mockResolvedValue(false);

  openInvalidationStream(vi.fn(), { renew, retryDelaysMs: [10, 100] });

  FakeEventSource.instances[0].failPermanently();
  await vi.advanceTimersByTimeAsync(10);
  expect(FakeEventSource.instances).toHaveLength(2);

  // Eine gescheiterte Rotation kann auch nur "Netz weg" heissen. Wer dann aufgibt, kommt ohne
  // Reload nie zurueck; wer sofort neu versucht, dreht sich. Also: erneut, aber langsamer.
  FakeEventSource.instances[1].failPermanently();
  await vi.advanceTimersByTimeAsync(10);
  expect(FakeEventSource.instances).toHaveLength(2); // noch nicht — 100 ms sind es
  await vi.advanceTimersByTimeAsync(90);
  expect(FakeEventSource.instances).toHaveLength(3);
});

test("close() during the backoff cancels the pending reconnect", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);
  const renew = vi.fn().mockResolvedValue(true);

  const stream = openInvalidationStream(vi.fn(), { renew, retryDelaysMs: [10] });
  FakeEventSource.instances[0].failPermanently();
  stream.close();
  await vi.advanceTimersByTimeAsync(100);

  // Sonst haette ein Abmelden mitten im Backoff einen Kanal wiederbelebt, den niemand mehr will.
  expect(renew).not.toHaveBeenCalled();
  expect(FakeEventSource.instances).toHaveLength(1);
});

test("a live connection resets the backoff", async () => {
  vi.useFakeTimers();
  vi.stubGlobal("EventSource", FakeEventSource);

  openInvalidationStream(vi.fn(), { retryDelaysMs: [10, 100] });

  FakeEventSource.instances[0].failPermanently();
  await vi.advanceTimersByTimeAsync(10);
  FakeEventSource.instances[1].emit("open");

  // Ohne das Zuruecksetzen waechst die Wartezeit ueber die Lebensdauer einer Sitzung hinweg,
  // obwohl der Kanal zwischendurch minutenlang lief.
  FakeEventSource.instances[1].failPermanently();
  await vi.advanceTimersByTimeAsync(10);
  expect(FakeEventSource.instances).toHaveLength(3);
});
