import { Popover } from "./ui";
import { CalendarInput } from "./calendar_input";

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
  if (uText && !(row.underlying ?? "").toUpperCase().includes(uText))
    return false;
  if (iText && !(row.issuer ?? "").toUpperCase().includes(iText)) return false;
  if (f.underlyings !== null) {
    if (!row.underlying || !f.underlyings.includes(row.underlying))
      return false;
  }
  if (f.issuers !== null) {
    if (!row.issuer || !f.issuers.includes(row.issuer)) return false;
  }
  if (f.from && (!row.lastTradingDate || row.lastTradingDate < f.from))
    return false;
  if (f.to && (!row.lastTradingDate || row.lastTradingDate > f.to))
    return false;
  return true;
}

function toggle(
  list: string[] | null,
  all: string[],
  value: string,
): string[] | null {
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
  const lists = [
    {
      label: "Underlying",
      options: underlyingOptions,
      selected: value.underlyings,
      text: value.uText,
      key: "underlyings" as const,
      textKey: "uText" as const,
    },
    {
      label: "Issuer",
      options: issuerOptions,
      selected: value.issuers,
      text: value.iText,
      key: "issuers" as const,
      textKey: "iText" as const,
    },
  ];
  return (
    <Popover label="Filters" active={isFilterActive(value)} width={420}>
      {(close) => (
        <>
          <div className="filter-grid">
            {lists.map((list) => (
              <div key={list.key}>
                <label className="field">
                  <span>{list.label}</span>
                  <input
                    aria-label={`Filter by ${list.label.toLowerCase()}`}
                    placeholder={`Search ${list.label.toLowerCase()}`}
                    value={list.text}
                    onChange={(e) =>
                      onChange({ ...value, [list.textKey]: e.target.value })
                    }
                  />
                </label>
                <div className="filter-options">
                  <label className="check-row">
                    <input
                      type="checkbox"
                      checked={list.selected === null}
                      onChange={() =>
                        onChange({
                          ...value,
                          [list.key]: list.selected === null ? [] : null,
                        })
                      }
                    />
                    All {list.label.toLowerCase()}s
                  </label>
                  {list.options.map((option) => (
                    <label className="check-row" key={option}>
                      <input
                        type="checkbox"
                        checked={
                          list.selected === null ||
                          list.selected.includes(option)
                        }
                        onChange={() =>
                          onChange({
                            ...value,
                            [list.key]: toggle(
                              list.selected,
                              list.options,
                              option,
                            ),
                          })
                        }
                      />
                      {option}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>
          <div className="filter-grid filter-dates">
            <CalendarInput
              ariaLabel="Last trading date from"
              value={value.from}
              onChange={(v) => onChange({ ...value, from: v })}
            />
            <CalendarInput
              ariaLabel="Last trading date to"
              value={value.to}
              onChange={(v) => onChange({ ...value, to: v })}
            />
          </div>
          {value.from && value.to && value.from > value.to && (
            <p className="field-error" role="alert">
              Start date must not be after end date.
            </p>
          )}
          <div className="popover-footer">
            <button
              className="btn btn-link"
              onClick={() => onChange(EMPTY_FILTER)}
            >
              Clear filters
            </button>
            <button className="btn" onClick={close}>
              Done
            </button>
          </div>
        </>
      )}
    </Popover>
  );
}
