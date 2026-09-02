import { CalendarInput } from "./calendar_input";
import { FilterPopover } from "./filter_popover";

/**
 * FILTER ▾ dropdown shared by the Watchlist CW table and the Registry table.
 * Filters rows by underlying, issuer (free-text OR checkbox), and a last-trading-date
 * range. Purely client-side; `null` for underlyings/issuers means "all".
 */

export interface FilterState {
  underlyings: string[] | null;
  issuers: string[] | null;
  uText: string;
  iText: string;
  from: string;
  to: string;
}

export const EMPTY_FILTER: FilterState = {
  underlyings: null,
  issuers: null,
  uText: "",
  iText: "",
  from: "",
  to: "",
};

export function isFilterActive(f: FilterState): boolean {
  return (
    f.underlyings !== null ||
    f.issuers !== null ||
    f.uText.trim() !== "" ||
    f.iText.trim() !== "" ||
    f.from !== "" ||
    f.to !== ""
  );
}

export interface FilterableRow {
  underlying?: string | null;
  issuer?: string | null;
  lastTradingDate?: string | null;
}

export function rowMatchesFilter(f: FilterState, row: FilterableRow): boolean {
  const uText = f.uText.trim().toUpperCase();
  const iText = f.iText.trim().toUpperCase();
  if (uText && !(row.underlying ?? "").toUpperCase().includes(uText)) return false;
  if (iText && !(row.issuer ?? "").toUpperCase().includes(iText)) return false;
  if (f.underlyings !== null) {
    if (!row.underlying || !f.underlyings.includes(row.underlying)) return false;
  }
  if (f.issuers !== null) {
    if (!row.issuer || !f.issuers.includes(row.issuer)) return false;
  }
  if (f.from && (!row.lastTradingDate || row.lastTradingDate < f.from)) return false;
  if (f.to && (!row.lastTradingDate || row.lastTradingDate > f.to)) return false;
  return true;
}

function toggle(list: string[] | null, all: string[], value: string): string[] | null {
  const current = list ?? all;
  const next = current.includes(value)
    ? current.filter((v) => v !== value)
    : [...current, value];
  return next.length === all.length ? null : next;
}

export function RegistryFilter({
  underlyingOptions,
  issuerOptions,
  value,
  onChange,
}: {
  underlyingOptions: string[];
  issuerOptions: string[];
  value: FilterState;
  onChange: (next: FilterState) => void;
}) {
  const groups = [
    { title: "UNDERLYING", options: underlyingOptions, selected: value.underlyings, key: "underlyings" as const, textKey: "uText" as const, text: value.uText, placeholder: "Enter symbol", label: "Filter by underlying symbol" },
    { title: "ISSUER", options: issuerOptions, selected: value.issuers, key: "issuers" as const, textKey: "iText" as const, text: value.iText, placeholder: "Enter issuer", label: "Filter by issuer" },
  ];
  return (
    <FilterPopover active={isFilterActive(value)} label="Instrument filters">
      <div className="filter-columns">
        {groups.map((group) => {
          const visible = group.options.filter((option) => option.toUpperCase().includes(group.text.trim().toUpperCase()));
          return (
            <section className="filter-column" key={group.key} aria-label={group.title}>
              <div className="filter-label">{group.title}</div>
              <input
                className="filter-search"
                type="text"
                placeholder={group.placeholder}
                aria-label={group.label}
                value={group.text}
                onChange={(e) => onChange({ ...value, [group.textKey]: e.target.value })}
              />
              <label className="filter-check filter-all">
                <input type="checkbox" checked={group.selected === null} aria-label={`All ${group.key}`}
                  onChange={() => onChange({ ...value, [group.key]: group.selected === null ? [] : null })} />
                All
              </label>
              <div className="filter-options" aria-label={`${group.title} options`} tabIndex={0}>
                {visible.map((option) => (
                  <label className="filter-check" key={option} title={option}>
                    <input type="checkbox" checked={group.selected === null || group.selected.includes(option)}
                      onChange={() => onChange({ ...value, [group.key]: toggle(group.selected, group.options, option) })} />
                    <span>{option}</span>
                  </label>
                ))}
              </div>
            </section>
          );
        })}
      </div>
      <div className="filter-date-section">
        <div className="filter-date-heading">
          <span className="filter-label">LAST TRADING DATE</span>
          <button type="button" className="filter-clear focus-ring" onClick={() => onChange(EMPTY_FILTER)}>CLEAR</button>
        </div>
        <div className="filter-dates">
          <div><div className="filter-date-label">From Date</div><CalendarInput ariaLabel="Last trading date from" value={value.from} onChange={(iso) => onChange({ ...value, from: iso })} /></div>
          <div><div className="filter-date-label">To Date</div><CalendarInput ariaLabel="Last trading date to" value={value.to} onChange={(iso) => onChange({ ...value, to: iso })} /></div>
        </div>
      </div>
    </FilterPopover>
  );
}
