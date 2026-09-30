import { act, renderHook } from "@testing-library/react";
import { expect, test } from "vitest";

import { useInstallPrompt } from "../lib/useInstallPrompt";

// The hook captures beforeinstallprompt at module level (it can fire before React mounts) and
// exposes it as canInstall; appinstalled hides the affordance for good.

type PromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

function fireBeforeInstallPrompt(outcome: "accepted" | "dismissed" = "accepted"): PromptEvent {
  const event = new Event("beforeinstallprompt", { cancelable: true }) as PromptEvent;
  event.prompt = async () => undefined;
  event.userChoice = Promise.resolve({ outcome });
  window.dispatchEvent(event);
  return event;
}

test("captures beforeinstallprompt, prompts once and resolves the choice", async () => {
  const { result } = renderHook(() => useInstallPrompt());
  act(() => {
    fireBeforeInstallPrompt("accepted");
  });
  expect(result.current.canInstall).toBe(true);

  let outcome = "";
  await act(async () => {
    outcome = await result.current.promptInstall();
  });
  expect(outcome).toBe("accepted");
  expect(result.current.canInstall).toBe(false); // the event is single-use

  await act(async () => {
    outcome = await result.current.promptInstall();
  });
  expect(outcome).toBe("dismissed"); // nothing left to prompt with
});

test("appinstalled clears the prompt and marks installed", () => {
  const { result } = renderHook(() => useInstallPrompt());
  act(() => {
    fireBeforeInstallPrompt();
  });
  expect(result.current.canInstall).toBe(true);
  act(() => {
    window.dispatchEvent(new Event("appinstalled"));
  });
  expect(result.current.canInstall).toBe(false);
  expect(result.current.installed).toBe(true);
});
