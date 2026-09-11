export function Change({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined || isNaN(value)) {
    return <span className="tnum text-subtle">—</span>;
  }

  // Canonical decimal fraction to percentage magnitude. Direction is already encoded by
  // the arrow and semantic colour, so a second +/- sign only adds visual noise.
  const pctValue = value * 100;
  const dir = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const glyph = dir === "up" ? "▲" : dir === "down" ? "▼" : "";
  const cls = dir === "up" ? "text-up" : dir === "down" ? "text-down" : "text-flat";

  return (
    <span className={`tnum ${cls}`} style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
      {glyph ? <span style={{ fontSize: "9px" }}>{glyph}</span> : null}
      <span>{Math.abs(pctValue).toFixed(2)}%</span>
    </span>
  );
}
