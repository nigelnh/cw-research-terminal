export function Change({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined || isNaN(value)) {
    return <span className="tnum text-subtle">—</span>;
  }

  const dir = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const glyph = dir === "up" ? "▲" : dir === "down" ? "▼" : "—";
  const cls = dir === "up" ? "text-up" : dir === "down" ? "text-down" : "text-flat";

  return (
    <span className={`tnum ${cls}`} style={{ display: "inline-flex", alignItems: "center", gap: "4px" }}>
      <span style={{ fontSize: "9px" }}>{glyph}</span>
      <span>{Math.abs(value).toFixed(2)}%</span>
    </span>
  );
}
