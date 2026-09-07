import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { RealtimePulse } from "@/domain/models";

export const REALTIME_FLASH_DURATION_MS = 1200;

/**
 * Re-renders every flashing cell when the tab is shown again.
 *
 * A hidden document freezes CSS animations and clamps `setTimeout` to about once a
 * minute, so the per-cell pulse-expiry timers do not fire while you are away. Without a
 * nudge on the way back, React never re-evaluates them and the whole board replays a
 * burst of long-dead flashes. One shared listener (not one per cell) drives it.
 */
let visibilityEpoch = 0;
const visibilityListeners = new Set<() => void>();
if (typeof document !== "undefined") {
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") return;
    visibilityEpoch += 1;
    visibilityListeners.forEach((fn) => fn());
  });
}

function useVisibilityEpoch(): number {
  const [epoch, setEpoch] = useState(visibilityEpoch);
  useEffect(() => {
    const onShow = () => setEpoch(visibilityEpoch);
    visibilityListeners.add(onShow);
    // The epoch can have moved between render and subscribe.
    onShow();
    return () => {
      visibilityListeners.delete(onShow);
    };
  }, []);
  return epoch;
}

/** Flash palette. Mirrors `MARKET_COLOR` so the wash can never contradict the digits. */
export type FlashTone = "up" | "down" | "flat" | "ceiling" | "floor" | "null";

export function RealtimeValue({
  pulse,
  tone,
  children,
  className = "",
  style,
  as = "span",
  title,
}: {
  pulse?: RealtimePulse;
  /**
   * Colour of the flash. The pulse still decides WHETHER to flash (the value moved);
   * this decides what colour, so a tick that lands on the ceiling washes magenta and one
   * at the reference washes flat-yellow instead of everything being green/red. Omit to
   * fall back to the pulse direction.
   */
  tone?: FlashTone;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  as?: "span" | "strong" | "small" | "td";
  title?: string;
}) {
  const [, expirePulse] = useState(0);
  // Reading the epoch re-runs the age check below the moment the tab is shown again, so a
  // pulse that "expired" while the timers were frozen is dropped instead of flashing.
  useVisibilityEpoch();
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
  // A price with no usable band ("null") keeps the direction wash rather than flashing grey.
  const flashTone = tone && tone !== "null" ? tone : activePulse?.direction;
  const flash = activePulse
    ? ` realtime-flash realtime-flash-${flashTone}`
    : "";
  const Tag = as;
  return (
    <Tag
      key={activePulse ? `${flashTone}:${activePulse.sequence}` : "baseline"}
      className={`${className}${flash}`.trim() || undefined}
      data-flash-direction={activePulse?.direction}
      data-flash-tone={activePulse ? flashTone : undefined}
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
  tone,
  children,
  className,
  style,
  as,
}: {
  value: number | null | undefined;
  resetKey?: string | null;
  tone?: FlashTone;
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
  return <RealtimeValue pulse={displayedPulse} tone={tone} className={className} style={style} as={as}>{children}</RealtimeValue>;
}
