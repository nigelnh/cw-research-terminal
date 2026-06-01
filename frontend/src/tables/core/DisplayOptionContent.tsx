import React from "react";
import { colors } from "@/design/tokens";

interface DisplayOptionContentProps {
  columns: { key: string; header: string }[];
  hiddenColumns: string[];
  onToggleColumn: (key: string) => void;
  onReset: () => void;
  onUnselectAll: () => void;
}

export function DisplayOptionContent({
  columns,
  hiddenColumns,
  onToggleColumn,
  onReset,
  onUnselectAll,
}: DisplayOptionContentProps) {
  const containerStyle: React.CSSProperties = {
    position: "absolute",
    top: "100%",
    right: 0,
    marginTop: 8,
    width: 450,
    backgroundColor: colors.panelBg,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    padding: 12, // Reduced padding for a tighter, premium look
    zIndex: 1000,
    boxShadow: "0 10px 25px rgba(0,0,0,0.5)",
    display: "flex",
    flexDirection: "column",
    gap: 10, // Reduced vertical element spacing gap
    color: colors.textSecondary,
    fontSize: 12,
    fontFamily: "'Inter', sans-serif",
  };

  const gridStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "6px 16px", // Muted horizontal and vertical gaps
  };

  const itemStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 6, // Reduced gap
    cursor: "pointer",
    padding: "2px 0", // Reduced spacing to cluster options
  };

  return (
    <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 2 }}>
        <div style={{ fontWeight: 600, fontSize: 11, color: colors.textSecondary, textTransform: "capitalize", letterSpacing: "0.04em" }}>
          Display Option
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          <button
            onClick={onReset}
            style={{
              backgroundColor: "transparent",
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
              borderRadius: 4,
              padding: "2px 8px",
              fontSize: 11,
              cursor: "pointer",
              fontWeight: 500,
              transition: "all 0.2s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = colors.textSecondary;
              e.currentTarget.style.color = colors.textPrimary;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = colors.border;
              e.currentTarget.style.color = colors.textSecondary;
            }}
          >
            Reset
          </button>
          <button
            onClick={onUnselectAll}
            style={{
              backgroundColor: "transparent",
              border: `1px solid ${colors.border}`,
              color: colors.textSecondary,
              borderRadius: 4,
              padding: "2px 8px",
              fontSize: 11,
              cursor: "pointer",
              fontWeight: 500,
              transition: "all 0.2s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = colors.textSecondary;
              e.currentTarget.style.color = colors.textPrimary;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = colors.border;
              e.currentTarget.style.color = colors.textSecondary;
            }}
          >
            Unselect All
          </button>
        </div>
      </div>
      <div style={gridStyle}>
        {columns.map((col) => {
          const isVisible = !hiddenColumns.includes(col.key);
          return (
            <label key={col.key} style={itemStyle}>
              <input
                type="checkbox"
                checked={isVisible}
                onChange={() => onToggleColumn(col.key)}
                style={{
                  accentColor: colors.textPrimary, // matches signature gold/yellow theme
                  cursor: "pointer",
                  margin: 0,
                }}
              />
              <span
                style={{
                  color: isVisible ? colors.textSecondary : colors.textMuted,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  fontSize: 11,
                }}
              >
                {col.header}
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
