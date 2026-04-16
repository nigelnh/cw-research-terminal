import React from "react";
import { colors } from "@/design/tokens";

interface DisplayOptionContentProps {
  columns: { key: string; header: string }[];
  hiddenColumns: string[];
  onToggleColumn: (key: string) => void;
  onReset: () => void;
}

export function DisplayOptionContent({
  columns,
  hiddenColumns,
  onToggleColumn,
  onReset,
}: DisplayOptionContentProps) {
  const containerStyle: React.CSSProperties = {
    position: "absolute",
    top: "100%",
    right: 0,
    marginTop: 8,
    width: 600,
    backgroundColor: colors.panelBg,
    border: `1px solid ${colors.border}`,
    borderRadius: 8,
    padding: 16,
    zIndex: 1000,
    boxShadow: "0 10px 25px rgba(0,0,0,0.5)",
    display: "flex",
    flexDirection: "column",
    gap: 16,
    color: colors.textSecondary,
    fontSize: 12,
  };

  const gridStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "10px 20px",
  };

  const itemStyle: React.CSSProperties = {
    display: "flex",
    alignItems: "center",
    gap: 8,
    cursor: "pointer",
    padding: "4px 0",
  };

  return (
    <div style={containerStyle} onClick={(e) => e.stopPropagation()}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <div style={{ fontWeight: 600 }}>Display Option</div>
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
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = colors.border;
          }}
        >
          Reset
        </button>
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
                style={{ accentColor: colors.textPrimary }}
              />
              <span
                style={{
                  color: isVisible ? colors.textPrimary : colors.textSecondary,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
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
