import { useEffect, useState } from "react";

// Chromium fires beforeinstallprompt at most once, possibly before React mounts: capture it at
// module level (MDN pattern) and notify subscribed hooks. appinstalled drops it again. iOS has
// no install prompt at all — callers show the manual Share → "Add to Home Screen" steps.
type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

let deferredPrompt: BeforeInstallPromptEvent | null = null;
let installed = false;
const subscribers = new Set<() => void>();
const notifyAll = () => subscribers.forEach((notify) => notify());

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault(); // no mini-infobar — install is offered in the UI ("kein Nag")
    deferredPrompt = event as BeforeInstallPromptEvent;
    notifyAll();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    installed = true;
    notifyAll();
  });
}

function detectStandalone(): boolean {
  if (typeof window === "undefined") return false;
  const viaMedia =
    typeof window.matchMedia === "function" &&
    window.matchMedia("(display-mode: standalone)").matches;
  const viaNavigator =
    "standalone" in navigator && (navigator as { standalone?: boolean }).standalone === true;
  return viaMedia || viaNavigator;
}

function detectIos(): boolean {
  if (typeof navigator === "undefined") return false;
  const ua = navigator.userAgent;
  // iPadOS reports as Mac; the touch-point check separates it from actual Macs.
  return /iPhone|iPad|iPod/.test(ua) || (ua.includes("Mac") && navigator.maxTouchPoints > 1);
}

export function useInstallPrompt(): {
  canInstall: boolean;
  installed: boolean;
  isIos: boolean;
  isStandalone: boolean;
  promptInstall: () => Promise<"accepted" | "dismissed">;
} {
  const [, bump] = useState(0);
  useEffect(() => {
    const notify = () => bump((n) => n + 1);
    subscribers.add(notify);
    return () => void subscribers.delete(notify);
  }, []);
  return {
    canInstall: deferredPrompt !== null,
    installed,
    isIos: detectIos(),
    isStandalone: detectStandalone(),
    promptInstall: async () => {
      const event = deferredPrompt;
      if (!event) return "dismissed";
      deferredPrompt = null; // the event is single-use
      await event.prompt();
      const choice = await event.userChoice;
      notifyAll();
      return choice.outcome;
    },
  };
}
