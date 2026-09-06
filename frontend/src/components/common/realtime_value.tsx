import { useEffect, useLayoutEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { RealtimePulse } from "@/domain/models";
import { prefersReducedMotion, spring } from "@/design/motion";

/** Directional value-wake duration. Kept in lockstep with `--flash-decay` in global.css —
 *  this timer clears the pulse state once the CSS animation has run. */
export const REALTIME_FLASH_DURATION_MS = 620;

export function RealtimeValue({
  pulse,
  children,
  className = "",
  style,
  as = "span",
  title,
}: {
  pulse?: RealtimePulse;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  as?: "span" | "strong" | "small" | "td";
  title?: string;
}) {
  const [, expirePulse] = useState(0);
  useEffect(() => {
    if (pulse?.startedAt === undefined) return;
    const remaining = REALTIME_FLASH_DURATION_MS - (Date.now() - pulse.startedAt);
    if (remaining <= 0) return;
    const timer = window.setTimeout(() => expirePulse((value) => value + 1), remaining + 1);
    return () => window.clearTimeout(timer);
  }, [pulse?.sequence, pulse?.startedAt]);
  const activePulse =
    pulse && (pulse.startedAt === undefined || Date.now() - pulse.startedAt <= REALTIME_FLASH_DURATION_MS)
      ? pulse
      : undefined;
  const flash = activePulse
    ? ` realtime-flash realtime-flash-${activePulse.direction}`
    : "";
  const Tag = as;
  return (
    <Tag
      key={activePulse ? `${activePulse.direction}:${activePulse.sequence}` : "baseline"}
      className={`${className}${flash}`.trim() || undefined}
      data-flash-direction={activePulse?.direction}
      data-flash-sequence={activePulse?.sequence}
      style={style}
      title={title}
    >
      {children}
    </Tag>
  );
}

/** For low-frequency REST polling surfaces that do not carry WebSocket pulse metadata. */
export function PolledRealtimeValue({
  value,
  resetKey,
  children,
  className,
  style,
  as,
}: {
  value: number | null | undefined;
  resetKey?: string | null;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  as?: "span" | "strong" | "small";
}) {
  const previous = useRef<number | null | undefined>(undefined);
  const previousReset = useRef(resetKey);
  const sequence = useRef(0);
  const [pulse, setPulse] = useState<RealtimePulse | undefined>();

  useEffect(() => {
    if (previousReset.current !== resetKey) {
      previousReset.current = resetKey;
      previous.current = value;
      setPulse(undefined);
      return;
    }
    const before = previous.current;
    previous.current = value;
    if (
      typeof before !== "number" ||
      !Number.isFinite(before) ||
      typeof value !== "number" ||
      !Number.isFinite(value) ||
      before === value
    ) {
      return;
    }
    sequence.current += 1;
    setPulse({
      sequence: sequence.current,
      direction: value > before ? "up" : "down",
      startedAt: Date.now(),
    });
  }, [resetKey, value]);

  const displayedPulse = previousReset.current === resetKey ? pulse : undefined;
  return <RealtimeValue pulse={displayedPulse} className={className} style={style} as={as}>{children}</RealtimeValue>;
}

/**
 * A polled value that *rolls* on change instead of only flashing — for the few large hero
 * numbers (the index card headline), not dense table cells. The outgoing value clips out
 * of frame in the direction of the move, the new one springs in from the opposite edge,
 * and a shortened directional wake decays behind it. Retargets cleanly if the value ticks
 * again mid-roll. Reduced motion → instant swap, wake only.
 */
export function RollingNumber({
  value,
  display,
  resetKey,
  className,
  style,
}: {
  value: number | null | undefined;
  display: string;
  resetKey?: string | null;
  className?: string;
  style?: CSSProperties;
}) {
  const hostRef = useRef<HTMLSpanElement>(null);
  const curRef = useRef<HTMLSpanElement>(null);
  const prevValue = useRef(value);
  const prevDisplay = useRef(display);
  const prevReset = useRef(resetKey);
  const animRef = useRef<Animation | null>(null);
  const [wake, setWake] = useState<"up" | "down" | null>(null);

  useLayoutEffect(() => {
    if (prevReset.current !== resetKey) {
      prevReset.current = resetKey;
      prevValue.current = value;
      prevDisplay.current = display;
      return;
    }
    const before = prevValue.current;
    const outgoing = prevDisplay.current;
    prevValue.current = value;
    prevDisplay.current = display;
    if (
      typeof before !== "number" ||
      typeof value !== "number" ||
      !Number.isFinite(before) ||
      !Number.isFinite(value) ||
      before === value
    ) {
      return;
    }

    const dir = value > before ? "up" : "down";
    setWake(dir);
    const wakeTimer = window.setTimeout(() => setWake(null), REALTIME_FLASH_DURATION_MS + 30);

    const cur = curRef.current;
    const host = hostRef.current;
    if (!cur || !host || prefersReducedMotion() || typeof cur.animate !== "function") {
      return () => window.clearTimeout(wakeTimer);
    }

    const d = dir === "down" ? 1 : -1;
    const ghost = document.createElement("span");
    ghost.className = "rolling-number-ghost";
    ghost.setAttribute("aria-hidden", "true");
    ghost.textContent = outgoing;
    host.appendChild(ghost);

    const { easing, duration } = spring("settle");
    ghost.animate(
      [{ transform: "translateY(0)" }, { transform: `translateY(${d * 108}%)` }],
      { duration: Math.round(duration * 0.7), easing: "cubic-bezier(.32, 0, .2, 1)", fill: "forwards" },
    );
    animRef.current?.cancel();
    animRef.current = cur.animate(
      [{ transform: `translateY(${-d * 108}%)` }, { transform: "translateY(0)" }],
      { duration, easing },
    );
    const drop = () => ghost.remove();
    animRef.current.addEventListener("finish", drop);
    animRef.current.addEventListener("cancel", drop);
    const guard = window.setTimeout(drop, duration + 140);

    return () => {
      window.clearTimeout(wakeTimer);
      window.clearTimeout(guard);
      ghost.remove();
    };
  }, [value, display, resetKey]);

  return (
    <span
      ref={hostRef}
      className={`rolling-number${wake ? ` realtime-flash realtime-flash-${wake}` : ""}${className ? ` ${className}` : ""}`}
      style={style}
    >
      <span ref={curRef} className="rolling-number-cur">{display}</span>
    </span>
  );
}
