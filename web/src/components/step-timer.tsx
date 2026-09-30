import { Trans } from "@lingui/react";
import { useEffect, useState } from "react";

import { Button } from "./button";

// A tap-able countdown for a step (T1). Starts paused at `minutes`; large digits for the kitchen.
export function StepTimer({ minutes }: { minutes: number }) {
  const [remaining, setRemaining] = useState(minutes * 60);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    setRemaining(minutes * 60);
    setRunning(false);
  }, [minutes]);

  useEffect(() => {
    if (!running) return;
    const id = window.setInterval(() => {
      setRemaining((value) => {
        if (value <= 1) {
          window.clearInterval(id);
          setRunning(false);
          return 0;
        }
        return value - 1;
      });
    }, 1000);
    return () => window.clearInterval(id);
  }, [running]);

  const mm = Math.floor(remaining / 60)
    .toString()
    .padStart(2, "0");
  const ss = (remaining % 60).toString().padStart(2, "0");
  const done = remaining === 0;

  return (
    <div className="flex items-center gap-3">
      <span className={`font-mono text-2xl tabular-nums ${done ? "text-laurus dark:text-laurus-dark" : "text-tinte dark:text-kalk"}`}>
        {mm}:{ss}
      </span>
      {done ? (
        <span className="font-medium text-laurus dark:text-laurus-dark">
          <Trans id="cook.timerDone" />
        </span>
      ) : (
        <Button type="button" onClick={() => setRunning((value) => !value)} className="px-3 py-1 text-sm">
          <Trans id={running ? "cook.pause" : "cook.start"} />
        </Button>
      )}
      <button
        type="button"
        onClick={() => {
          setRemaining(minutes * 60);
          setRunning(false);
        }}
        className="text-sm text-laurus dark:text-laurus-dark hover:underline"
      >
        <Trans id="cook.reset" />
      </button>
    </div>
  );
}
