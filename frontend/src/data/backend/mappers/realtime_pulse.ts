import type { RealtimePulseMap } from "@/domain/models";

type NumericRecord = Record<string, number | null | undefined>;

/**
 * Preserve prior markers and advance only fields changed by an incremental patch.
 * Null-to-value is treated as baseline establishment, not a market movement.
 */
export function mergeRealtimePulses(
  existing: RealtimePulseMap | undefined,
  before: NumericRecord,
  after: NumericRecord,
  touched: readonly string[],
  enabled = true,
): RealtimePulseMap | undefined {
  if (!enabled) return undefined;
  let next = existing;
  for (const field of touched) {
    const previous = before[field];
    const current = after[field];
    if (
      typeof previous !== "number" ||
      !Number.isFinite(previous) ||
      typeof current !== "number" ||
      !Number.isFinite(current) ||
      previous === current
    ) {
      continue;
    }
    if (next === existing) next = { ...(existing ?? {}) };
    (next as RealtimePulseMap)[field] = {
      sequence: (existing?.[field]?.sequence ?? 0) + 1,
      direction: current > previous ? "up" : "down",
      startedAt: Date.now(),
    };
  }
  return next;
}
