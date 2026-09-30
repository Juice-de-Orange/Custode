import { useEffect, useState } from "react";

// Shared connectivity hook (UX_KONZEPT §2: quiet sync/offline indicator — never a modal).
// Pure state — side effects on reconnect (e.g. the shopping outbox push) stay with the caller.
export function useOnline(): boolean {
  const [online, setOnline] = useState(() =>
    typeof navigator === "undefined" ? true : navigator.onLine,
  );
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return online;
}
