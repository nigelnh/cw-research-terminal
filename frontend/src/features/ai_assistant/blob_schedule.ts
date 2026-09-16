import { useEffect, useRef, useState } from "react";

export type BlobVisualState = "idle" | "code" | "boba" | "sleep";
export type BlobSchedulePhase = "work" | "boba" | "sleep";

const ICT_TIME_ZONE = "Asia/Ho_Chi_Minh";
const ICT_CLOCK = new Intl.DateTimeFormat("en-GB", {
  timeZone: ICT_TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

const IDLE_MIN_MS = 18_000;
const IDLE_MAX_MS = 30_000;
const CODE_MIN_MS = 60_000;
const CODE_MAX_MS = 105_000;

function ictClock(now: Date): { hour: number; minute: number; second: number } {
  const parts = ICT_CLOCK.formatToParts(now);
  const value = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value ?? 0);
  return { hour: value("hour"), minute: value("minute"), second: value("second") };
}

/** Daily Blob schedule in Vietnam time, independent of the browser's local timezone. */
export function getBlobSchedulePhase(now: Date): BlobSchedulePhase {
  const { hour, minute } = ictClock(now);
  const minuteOfDay = hour * 60 + minute;

  if ((minuteOfDay >= 8 * 60 && minuteOfDay < 11 * 60 + 30) ||
      (minuteOfDay >= 13 * 60 && minuteOfDay < 15 * 60)) {
    return "work";
  }
  if (minuteOfDay >= 11 * 60 + 30 && minuteOfDay < 12 * 60) return "boba";
  return "sleep";
}

/** Time remaining before the next fixed schedule boundary in ICT. */
export function millisecondsUntilNextBlobPhase(now: Date): number {
  const { hour, minute, second } = ictClock(now);
  const elapsed = (((hour * 60 + minute) * 60 + second) * 1000) + now.getMilliseconds();
  const boundaries = [8 * 60, 11 * 60 + 30, 12 * 60, 13 * 60, 15 * 60]
    .map((boundaryMinute) => boundaryMinute * 60 * 1000);
  const next = boundaries.find((boundary) => boundary > elapsed);
  if (next !== undefined) return next - elapsed;
  return (24 * 60 * 60 * 1000 - elapsed) + 8 * 60 * 60 * 1000;
}

function randomBetween(min: number, max: number, random: () => number): number {
  return min + Math.floor(Math.min(0.999999, Math.max(0, random())) * (max - min + 1));
}

/** Coding always lasts longer than an idle turn; timing within each range is random. */
export function workStateDurationMs(state: "idle" | "code", random: () => number = Math.random): number {
  return state === "code"
    ? randomBetween(CODE_MIN_MS, CODE_MAX_MS, random)
    : randomBetween(IDLE_MIN_MS, IDLE_MAX_MS, random);
}

function stateForNewPhase(phase: BlobSchedulePhase, random: () => number): BlobVisualState {
  if (phase === "boba") return "boba";
  if (phase === "sleep") return "sleep";
  // Start most work blocks at the MacBook; subsequent turns alternate so both
  // work poses are guaranteed to appear.
  return random() < 0.75 ? "code" : "idle";
}

/**
 * Keeps one shared Blob state for the launcher and the open assistant panel.
 * Timers stop at phase boundaries, and focus/visibility events correct stale timers
 * after a sleeping browser tab wakes up.
 */
export function useScheduledBlobState(random: () => number = Math.random): BlobVisualState {
  const initial = useRef<{ phase: BlobSchedulePhase; state: BlobVisualState } | null>(null);
  if (initial.current === null) {
    const phase = getBlobSchedulePhase(new Date());
    initial.current = { phase, state: stateForNewPhase(phase, random) };
  }
  const [state, setState] = useState<BlobVisualState>(initial.current.state);

  useEffect(() => {
    let stopped = false;
    let timeoutId: number | undefined;
    let currentPhase = initial.current?.phase ?? getBlobSchedulePhase(new Date());
    let currentState = initial.current?.state ?? stateForNewPhase(currentPhase, random);

    const schedule = (advanceWorkState: boolean) => {
      if (stopped) return;
      const now = new Date();
      const phase = getBlobSchedulePhase(now);

      if (phase !== currentPhase) {
        currentPhase = phase;
        currentState = stateForNewPhase(phase, random);
      } else if (phase === "work" && advanceWorkState) {
        currentState = currentState === "code" ? "idle" : "code";
      } else if (phase !== "work") {
        currentState = stateForNewPhase(phase, random);
      }

      setState(currentState);
      const phaseRemaining = millisecondsUntilNextBlobPhase(now);
      const stateRemaining = phase === "work"
        ? workStateDurationMs(currentState as "idle" | "code", random)
        : phaseRemaining;
      timeoutId = window.setTimeout(
        () => schedule(phase === "work"),
        Math.max(1, Math.min(phaseRemaining, stateRemaining)),
      );
    };

    const resync = () => {
      if (document.visibilityState === "hidden") return;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      // Re-evaluate the phase immediately after the tab or window wakes. A work
      // pose may be re-picked; fixed boba/sleep phases stay deterministic.
      currentPhase = getBlobSchedulePhase(new Date());
      currentState = stateForNewPhase(currentPhase, random);
      schedule(false);
    };

    schedule(false);
    document.addEventListener("visibilitychange", resync);
    window.addEventListener("focus", resync);
    return () => {
      stopped = true;
      if (timeoutId !== undefined) window.clearTimeout(timeoutId);
      document.removeEventListener("visibilitychange", resync);
      window.removeEventListener("focus", resync);
    };
  }, [random]);

  return state;
}
