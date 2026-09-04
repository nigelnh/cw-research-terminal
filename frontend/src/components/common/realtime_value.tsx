import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";
import type { RealtimePulse } from "@/domain/models";

export const REALTIME_FLASH_DURATION_MS = 1200;

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
