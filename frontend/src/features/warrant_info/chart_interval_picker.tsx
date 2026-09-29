import type React from "react";
import {
  DAY_INTERVALS,
  INTRADAY_INTERVALS,
  type InstrumentChartInterval,
} from "@/domain/historical/chart_intervals";

/** Candle-interval switch for the instrument chart: intraday granularities, then day-or-longer. */
export function ChartIntervalPicker({
  value,
  onChange,
  note,
}: {
  value: InstrumentChartInterval;
  onChange: (interval: InstrumentChartInterval) => void;
  note?: string | null;
}) {
  const button = (id: InstrumentChartInterval): React.CSSProperties => ({
    padding: "2px 7px",
    border: "none",
    borderRadius: 2,
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: 10.5,
    background: value === id ? "var(--panel-tab-active)" : "transparent",
    color: value === id ? "var(--t-92)" : "var(--t-55)",
  });
  const group = (label: string, items: readonly InstrumentChartInterval[]) => (
    <div role="group" aria-label={label} style={{ display: "flex", alignItems: "center", gap: 1 }}>
      <span style={{ fontSize: 9.5, color: "var(--t-42)", marginRight: 5, letterSpacing: 0.4 }}>{label}</span>
      {items.map((id) => (
        <button key={id} type="button" aria-pressed={value === id} onClick={() => onChange(id)} style={button(id)}>
          {id}
        </button>
      ))}
    </div>
  );
  return (
    <div
      className="mono"
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "4px 8px",
        borderBottom: "1px solid var(--border)",
        flexWrap: "wrap",
        flexShrink: 0,
      }}
    >
      {group("INTRADAY", INTRADAY_INTERVALS)}
      {group("DAYS", DAY_INTERVALS)}
      {note && <span style={{ fontSize: 10, color: "var(--t-42)", marginLeft: "auto" }}>{note}</span>}
    </div>
  );
}
