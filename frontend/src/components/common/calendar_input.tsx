/** Native calendar supports keyboard date entry. Values remain ISO calendar dates. */
export function CalendarInput({
  value,
  onChange,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  return (
    <label className="field">
      <span>{ariaLabel}</span>
      <input
        type="date"
        aria-label={ariaLabel}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}
