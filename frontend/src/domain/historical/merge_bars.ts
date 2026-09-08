import type { HistoricalBar } from "@/domain/models";

export function mergeHistoricalBars(base: HistoricalBar[], live: HistoricalBar[], displaySession?: string): HistoricalBar[] {
  const byTime = new Map(base.map(bar => [bar.date, bar]));
  for (const bar of live) {
    if (displaySession && bar.sessionDate !== displaySession) continue;
    const previous = byTime.get(bar.date);
    if (previous && previous.complete !== false && !["OBSERVED_SESSION", "REALTIME_SESSION"].includes(previous.source ?? "")) continue;
    if (previous?.asOf && (!bar.asOf || Date.parse(bar.asOf) < Date.parse(previous.asOf))) continue;
    byTime.set(bar.date, bar);
  }
  return [...byTime.values()].sort((a, b) => a.date.localeCompare(b.date));
}

export function aggregateProvenance(bars: HistoricalBar[]): Partial<HistoricalBar> {
  const sources = [...new Set(bars.map(b => b.source ?? "UNKNOWN"))];
  const bases = [...new Set(bars.map(b => b.priceBasis))];
  return {
    source: sources.length === 1 ? sources[0] : `MIXED (${sources.join(", ")})`,
    priceBasis: bases.length === 1 ? bases[0] : null,
    sessionDate: bars[bars.length - 1]?.sessionDate,
    asOf: bars.map(b => b.asOf).filter((s): s is string => Boolean(s)).sort((a, b) => Date.parse(a) - Date.parse(b)).slice(-1)[0] ?? null,
    complete: bars.every(b => b.complete !== false && b.source !== "OBSERVED_SESSION"),
    value: bars.every(b => b.value != null) ? bars.reduce((sum, b) => sum + b.value!, 0) : null,
  };
}
