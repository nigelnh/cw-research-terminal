import React from "react";
import { colors } from "@/design/tokens";

interface TableFilterContentProps {
  underlyings: string[];
  selectedUnderlyings: string[];
  onSelectUnderlyings: (vals: string[]) => void;
  onReset: () => void;
}

export function TableFilterContent({
  underlyings,
  selectedUnderlyings,
  onSelectUnderlyings,
  onReset,
}: TableFilterContentProps) {
  const containerStyle: React.CSSProperties = {
    position: "absolute",
    top: "100%",
    right: 0,
    marginTop: 8,
    width: 170, // Sleek, single-column width for underlying selector
    backgroundColor: colors.panelBg,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    padding: "12px 14px",
    zIndex: 1000,
    boxShadow: "0 12px 30px rgba(0,0,0,0.65)",
    display: "flex",
    flexDirection: "column",
    gap: 12,
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: "'Inter', sans-serif",
  };

  const columnTitleStyle: React.CSSProperties = {
    fontSize: 11,
    fontWeight: 600,
    color: colors.textSecondary,
    textTransform: "capitalize",
    letterSpacing: "0.04em",
  };

  const scrollableBoxStyle: React.CSSProperties = {
    backgroundColor: "rgba(0, 0, 0, 0.25)",
    border: `1px solid ${colors.border}`,
    borderRadius: 6,
    padding: "6px 10px 6px 10px",
    height: 140, // Standard scroll height
    overflowY: "auto",
    display: "flex",
    flexDirection: "column",
    gap: 4,
    width: "100%",
    boxSizing: "border-box",
  };

  const optionLabelStyle = (isActive: boolean): React.CSSProperties => ({
    display: "flex",
    alignItems: "center",
    gap: 5,
    cursor: "pointer",
    fontSize: 11,
    color: isActive ? colors.textSecondary : colors.textMuted,
    padding: "3px 0",
    transition: "color 0.15s ease",
    whiteSpace: "nowrap",
    width: "100%",
  });

  return (
    <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
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
                  accentColor: colors.textPrimary,
                  cursor: "pointer",
                  margin: 0,
                }}
              />
              <span>{item}</span>
            </label>
          );
        })}
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
        Reset
      </button>
    </div>
  );
}
