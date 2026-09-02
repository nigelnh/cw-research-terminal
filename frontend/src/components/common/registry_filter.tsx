import { useState } from "react";
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

const LABEL: React.CSSProperties = {
  fontSize: 9.5,
  letterSpacing: "0.06em",
  color: "var(--t-50)",
  marginBottom: 6,
};
const CHECK_ROW: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 6,
  padding: "3px 0",
  fontSize: 11,
  cursor: "pointer",
  color: "var(--t-80)",
};
const TEXT_INPUT: React.CSSProperties = {
  width: "100%",
  background: "var(--bg)",
  border: "1px solid var(--border-26)",
  padding: "4px 8px",
  fontSize: 11,
  color: "var(--t-85)",
  marginBottom: 6,
  fontFamily: "inherit",
  outline: "none",
  boxSizing: "border-box",
};
/** Bounded, internally-scrolling checkbox list so a long options set can't grow the popover. */
const SCROLL_LIST: React.CSSProperties = {
  maxHeight: 132,
  overflowY: "auto",
};

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
  const [open, setOpen] = useState(false);
  const uChecked = (u: string) => value.underlyings === null || value.underlyings.includes(u);
  const iChecked = (i: string) => value.issuers === null || value.issuers.includes(i);

  return (
    <div
      style={{ marginLeft: "auto", position: "relative" }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        className="focus-ring"
        aria-expanded={open}
        style={{
          padding: "4px 10px",
          border: "1px solid var(--border-30)",
          borderRadius: 2,
          background: isFilterActive(value) ? "var(--panel-active)" : "transparent",
          color: "var(--t-75)",
          cursor: "pointer",
          fontFamily: "inherit",
          fontSize: 10.5,
        }}
      >
        FILTER ▾
      </button>
      {open && (
        <div style={{ position: "absolute", right: 0, top: "100%", paddingTop: 6, zIndex: 55 }}>
        <div
          className="mono"
          style={{
            background: "var(--panel-2)",
            border: "1px solid var(--border-30)",
            padding: 14,
            width: 420,
            boxShadow: "0 8px 24px rgba(0,0,0,0.5)",
          }}
        >
          <div style={{ display: "flex", gap: 20, marginBottom: 12, alignItems: "flex-start" }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={LABEL}>UNDERLYING</div>
              <input
                type="text"
                placeholder="Enter symbol"
                aria-label="Filter by underlying symbol"
                value={value.uText}
                onChange={(e) => onChange({ ...value, uText: e.target.value })}
                style={TEXT_INPUT}
              />
              <div style={SCROLL_LIST}>
                <label style={CHECK_ROW}>
                  <input
                    type="checkbox"
                    checked={value.underlyings === null}
                    onChange={() =>
                      onChange({ ...value, underlyings: value.underlyings === null ? [] : null })
                    }
                  />
                  All
                </label>
                {underlyingOptions.map((u) => (
                  <label key={u} style={CHECK_ROW}>
                    <input
                      type="checkbox"
                      checked={uChecked(u)}
                      onChange={() =>
                        onChange({ ...value, underlyings: toggle(value.underlyings, underlyingOptions, u) })
                      }
                    />
                    {u}
                  </label>
                ))}
              </div>
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={LABEL}>ISSUER</div>
              <input
                type="text"
                placeholder="Enter issuer"
                aria-label="Filter by issuer"
                value={value.iText}
                onChange={(e) => onChange({ ...value, iText: e.target.value })}
                style={TEXT_INPUT}
              />
              <div style={SCROLL_LIST}>
                <label style={CHECK_ROW}>
                  <input
                    type="checkbox"
                    checked={value.issuers === null}
                    onChange={() =>
                      onChange({ ...value, issuers: value.issuers === null ? [] : null })
                    }
                  />
                  All
                </label>
                {issuerOptions.map((i) => (
                  <label key={i} style={CHECK_ROW}>
                    <input
                      type="checkbox"
                      checked={iChecked(i)}
                      onChange={() =>
                        onChange({ ...value, issuers: toggle(value.issuers, issuerOptions, i) })
                      }
                    />
                    {i}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <div style={{ borderTop: "1px solid var(--border)", paddingTop: 10 }}>
            <div style={LABEL}>LAST TRADING DATE</div>
            <div style={{ display: "flex", gap: 8 }}>
              <CalendarInput
                ariaLabel="Last trading date from"
                value={value.from}
                onChange={(iso) => onChange({ ...value, from: iso })}
              />
              <CalendarInput
                ariaLabel="Last trading date to"
                value={value.to}
                onChange={(iso) => onChange({ ...value, to: iso })}
              />
              <button
                type="button"
                onClick={() => onChange(EMPTY_FILTER)}
                style={{
                  padding: "4px 12px",
                  border: "none",
                  borderRadius: 2,
                  background: "var(--panel-active)",
                  color: "var(--t-85)",
                  cursor: "pointer",
                  fontSize: 10.5,
                  fontFamily: "inherit",
                }}
              >
                CLEAR
              </button>
            </div>
          </div>
        </div>
        </div>
      )}
    </div>
  );
}
