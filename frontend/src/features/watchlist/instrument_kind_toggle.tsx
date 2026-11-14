/** Which instruments the watchlist shows: both kinds, stocks only, or covered warrants only. */
export type InstrumentKindView = "all" | "stock" | "cw";

const OPTIONS: { value: InstrumentKindView; label: string; title: string }[] = [
  { value: "all", label: "ALL", title: "Show stocks and covered warrants" },
  { value: "stock", label: "STOCK", title: "Show stocks only" },
  { value: "cw", label: "CW", title: "Show covered warrants only" },
];

/**
 * ALL / STOCK / CW segmented toggle beside the watchlist's FILTER ▾. A view filter only:
 * hidden rows keep their place in the saved row order, so switching back to ALL shows the
 * same grouping as before.
 */
export function InstrumentKindToggle({
  value,
  onChange,
}: {
  value: InstrumentKindView;
  onChange: (next: InstrumentKindView) => void;
}) {
  return (
    <div className="kind-toggle" role="group" aria-label="Show instruments">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className="focus-ring"
          aria-pressed={value === option.value}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
