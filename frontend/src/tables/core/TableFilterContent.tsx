import React, { useLayoutEffect, useRef, useState } from "react";
import { colors } from "@/design/tokens";

interface DateInputProps {
  value: string;
  onChange: (val: string) => void;
}

function DateInput({ value, onChange }: DateInputProps) {
  const [inputValue, setInputValue] = useState("");

  // Sync prop value (YYYY-MM-DD) to local formatted value (DD/MM/YYYY)
  React.useEffect(() => {
    if (!value) {
      setInputValue("");
      return;
    }
    const parts = value.split("-");
    if (parts.length === 3) {
      const [year, month, day] = parts;
      setInputValue(`${day}/${month}/${year}`);
    } else {
      setInputValue(value);
    }
  }, [value]);

  const handleTextChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value;
    
    // Filter non-digits and insert slashes automatically for a high-fidelity experience
    const clean = val.replace(/\D/g, "");
    let formatted = "";
    if (clean.length > 0) {
      formatted += clean.substring(0, 2);
    }
    if (clean.length > 2) {
      formatted += "/" + clean.substring(2, 4);
    }
    if (clean.length > 4) {
      formatted += "/" + clean.substring(4, 8);
    }
    
    setInputValue(formatted);

    // Propagate changes to the parent filter when a complete date is entered
    if (formatted.length === 10) {
      const parts = formatted.split("/");
      if (parts.length === 3) {
        const [day, month, year] = parts;
        const d = parseInt(day, 10);
        const m = parseInt(month, 10);
        const y = parseInt(year, 10);
        if (d >= 1 && d <= 31 && m >= 1 && m <= 12 && y >= 1900 && y <= 2100) {
          onChange(`${year}-${month.padStart(2, "0")}-${day.padStart(2, "0")}`);
          return;
        }
      }
    }
    // Erase or incomplete input propagates an empty filter parameter
    if (val === "") {
      onChange("");
    }
  };

  const handleNativeDateChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.value; // YYYY-MM-DD
    onChange(val);
  };

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        backgroundColor: "rgba(0, 0, 0, 0.25)",
        border: `1px solid ${colors.border}`,
        borderRadius: 6,
        padding: "4px 10px",
        cursor: "text",
        position: "relative",
        height: 32,
        boxSizing: "border-box",
        transition: "border-color 0.2s, background-color 0.2s",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "rgba(255, 255, 255, 0.25)";
        e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = colors.border;
        e.currentTarget.style.backgroundColor = "rgba(0, 0, 0, 0.25)";
      }}
    >
      {/* 1. Visible Text Input (DD/MM/YYYY placeholder and manual typing) */}
      <input
        type="text"
        placeholder="DD/MM/YYYY"
        value={inputValue}
        onChange={handleTextChange}
        style={{
          backgroundColor: "transparent",
          border: "none",
          color: colors.textPrimary,
          fontSize: "11px",
          fontFamily: "'Inter', sans-serif",
          outline: "none",
          width: "calc(100% - 22px)",
          height: "100%",
          padding: 0,
          cursor: "text",
        }}
      />

      {/* 2. Calendar Trigger Icon Area (Only clicking this part opens the native picker calendar) */}
      <div
        style={{
          position: "relative",
          width: 20,
          height: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          cursor: "pointer",
        }}
      >
        <span
          className="material-symbols-outlined"
          style={{
            fontSize: 15,
            color: colors.textSecondary,
            pointerEvents: "none",
          }}
        >
          calendar_today
        </span>
        {/* Hidden native picker overlaid exactly over the calendar icon area */}
        <input
          type="date"
          value={value}
          onChange={handleNativeDateChange}
          style={{
            position: "absolute",
            top: 0,
            left: 0,
            width: "100%",
            height: "100%",
            opacity: 0,
            cursor: "pointer",
            colorScheme: "dark",
          }}
        />
      </div>
    </div>
  );
}

interface TableFilterContentProps {
  underlyings: string[];
  selectedUnderlyings: string[];
  onSelectUnderlyings: (vals: string[]) => void;

  fromDate: string;
  toDate: string;
  onChangeFromDate: (val: string) => void;
  onChangeToDate: (val: string) => void;

  onReset: () => void;
  isDateOnly?: boolean;
}

export function TableFilterContent({
  underlyings,
  selectedUnderlyings,
  onSelectUnderlyings,
  fromDate,
  toDate,
  onChangeFromDate,
  onChangeToDate,
  onReset,
  isDateOnly = false,
}: TableFilterContentProps) {
  const rightColumnRef = useRef<HTMLDivElement>(null);
  const [rightHeight, setRightHeight] = useState<number>(140); // Safe fallback height

  // Measure right column's content height dynamically after rendering to align columns perfectly
  useLayoutEffect(() => {
    if (rightColumnRef.current) {
      setRightHeight(rightColumnRef.current.offsetHeight);
    }
  }, [selectedUnderlyings, fromDate, toDate]); // Re-measure if contents or parameters change

  const containerStyle: React.CSSProperties = {
    position: "absolute",
    top: "100%",
    right: 0,
    marginTop: 8,
    width: isDateOnly ? 170 : 320, // Snug width for date-only calendars (Holiday/Dividend) vs standard underlyings
    backgroundColor: colors.panelBg,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    padding: isDateOnly ? "12px 14px" : "16px 18px", // Balanced padding
    zIndex: 1000,
    boxShadow: "0 12px 30px rgba(0,0,0,0.65)",
    display: "flex",
    flexDirection: "column",
    gap: 16, // Spacing between elements
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: "'Inter', sans-serif",
  };

  const columnsContainerStyle: React.CSSProperties = {
    display: "flex",
    flexDirection: "row",
    gap: 20, // Spacious sub-container columns
    alignItems: "flex-start", // Revert to top alignment so the left column never stretches the popover container
  };

  const leftColumnStyle: React.CSSProperties = {
    flex: 1, // Balanced 2:2 ratio
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  };

  const rightColumnStyle: React.CSSProperties = {
    flex: 1, // Balanced 2:2 ratio
    minWidth: 0,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  };

  const columnTitleStyle: React.CSSProperties = {
    fontSize: 11,
    fontWeight: 600,
    color: colors.textSecondary, // Changed to textSecondary color
    textTransform: "uppercase",
    letterSpacing: "0.04em",
  };

  const scrollableBoxStyle: React.CSSProperties = {
    backgroundColor: "rgba(0, 0, 0, 0.25)",
    border: `1px solid ${colors.border}`,
    borderRadius: 6,
    padding: "6px 10px 6px 10px", // Reduced padding-right to tighten empty space
    height: rightHeight, // Dynamically set to match measured right column height with single-pixel accuracy
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 4, // Tighter gap between radio rows to keep it compact
    width: "100%",
    boxSizing: "border-box",
  };

  const optionLabelStyle = (isActive: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 5, // Reduced gap between checkbox and text
    cursor: "pointer",
    fontSize: 11,
    color: isActive ? colors.textSecondary : colors.textMuted, // Changed to textSecondary when active, and textMuted when inactive
    padding: "3px 0", // Tighter vertical padding to prevent empty spaces
    transition: "color 0.15s ease",
    whiteSpace: "nowrap",
    width: "100%",
  });

  return (
    <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
      <div style={columnsContainerStyle}>
        {/* Sub container 1: Underlying Symbols (Hidden for Date Only Calendars) */}
        {!isDateOnly && (
          <div style={leftColumnStyle}>
            <div style={columnTitleStyle}>Underlying</div>
            <div style={scrollableBoxStyle} className="custom-scrollbar">
              {["All", ...underlyings].map((item) => {
                const isAllSelected = selectedUnderlyings.includes("All");
                const isActive = item === "All" ? isAllSelected : (isAllSelected || selectedUnderlyings.includes(item));

                const handleToggle = () => {
                  if (item === "All") {
                    if (isAllSelected) {
                      onSelectUnderlyings([]);
                    } else {
                      onSelectUnderlyings(["All", ...underlyings]);
                    }
                  } else {
                    let next = [...selectedUnderlyings];
                    if (isAllSelected) {
                      // Clicking an individual option when "All" was checked unchecks "All" and keeps all other individual options checked
                      next = underlyings.filter((u) => u !== item);
                    } else {
                      if (next.includes(item)) {
                        next = next.filter((u) => u !== item);
                      } else {
                        next.push(item);
                      }
                    }
                    onSelectUnderlyings(next);
                  }
                };

                return (
                  <label key={item} style={optionLabelStyle(isActive)}>
                    <input
                      type="checkbox"
                      checked={isActive}
                      onChange={handleToggle}
                      style={{
                        accentColor: colors.textPrimary, // matches main gold color scheme
                        cursor: "pointer",
                        margin: 0,
                      }}
                    />
                    <span>{item}</span>
                  </label>
                );
              })}
            </div>
          </div>
        )}

        {/* Sub container 2: Expiry / Maturity Dates Range */}
        <div style={rightColumnStyle}>
          <div style={columnTitleStyle}>{isDateOnly ? "Date" : "Maturity Date"}</div>
          <div ref={rightColumnRef} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            <div>
              <div style={{ fontSize: 10, color: "rgba(255, 255, 255, 0.4)", marginBottom: 4, fontWeight: 500 }}>
                From Date
              </div>
              <DateInput
                value={fromDate}
                onChange={onChangeFromDate}
              />
            </div>
            <div>
              <div style={{ fontSize: 10, color: "rgba(255, 255, 255, 0.4)", marginBottom: 4, fontWeight: 500 }}>
                To Date
              </div>
              <DateInput
                value={toDate}
                onChange={onChangeToDate}
              />
            </div>
            <button
              onClick={onReset}
              style={{
                backgroundColor: "transparent",
                border: `1px solid ${colors.border}`,
                color: colors.textSecondary,
                borderRadius: 6,
                padding: "6px 12px",
                fontSize: 11,
                cursor: "pointer",
                fontWeight: 500,
                transition: "all 0.2s",
                marginTop: 8,
                textAlign: "center",
                width: "100%",
                boxSizing: "border-box",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = colors.textSecondary;
                e.currentTarget.style.color = colors.textPrimary;
                e.currentTarget.style.backgroundColor = "rgba(255, 255, 255, 0.03)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = colors.border;
                e.currentTarget.style.color = colors.textSecondary;
                e.currentTarget.style.backgroundColor = "transparent";
              }}
            >
              Clear
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
