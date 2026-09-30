import { useEffect } from "react";

// Keep the screen awake during cook mode (T1). Graceful: a no-op where the Wake Lock API is
// unavailable or permission is denied. Re-acquires on tab re-focus (the lock drops when hidden).
export function useWakeLock(active: boolean): void {
  useEffect(() => {
    if (!active || typeof navigator === "undefined" || !("wakeLock" in navigator)) return;

    let sentinel: WakeLockSentinel | null = null;
    let released = false;

    const acquire = async () => {
      try {
        sentinel = await navigator.wakeLock.request("screen");
      } catch {
        // not supported / permission denied -> silently run without a wake lock
      }
    };

    const onVisibility = () => {
      if (document.visibilityState === "visible" && !released) void acquire();
    };

    void acquire();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      released = true;
      document.removeEventListener("visibilitychange", onVisibility);
      void sentinel?.release().catch(() => undefined);
    };
  }, [active]);
}
