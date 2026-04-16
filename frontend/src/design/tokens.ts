/**
 * Design tokens - colors, fonts, sizing constants
 * Migrated from Streamlit config.py
 */

export const colors = {
  background: "#0E1117",
  panelBg: "#1E1E1E",
  border: "rgba(255, 255, 255, 0.1)",
  borderSubtle: "rgba(255, 255, 255, 0.06)",
  textPrimary: "#F3BA2F",
  textSecondary: "#FFFFFF",
  textMuted: "#BCBCBC",
  increase: "#0ECB81",
  decrease: "#F6465D",
  purple: "#C77DFF",
  cyan: "#00FFFF",
  blue: "#1E90FF",
  yellow: "#FFD700",
  volData: "#C4C4C4",
  highlightGreen: "rgba(82, 198, 126, 0.3)",
} as const;

export const fonts = {
  display: "'Inter', sans-serif",
  mono: "'JetBrains Mono', monospace",
} as const;

/**
 * Table sizing configuration
 * Fixed pixel values for consistent rendering
 */
export const tableConfig = {
  headerHeight: 32,
  rowHeight: 40,
  maxRows: 10,
  fontSize: 14,
  headerFontSize: 13,
} as const;

/**
 * Equity table column definitions
 * Each column has a fixed pixel width
 */
export const equityColumns = {
  Symbol: { width: 70, align: "left" as const, color: colors.textSecondary },
  Ceil: { width: 70, align: "right" as const, color: colors.purple },
  Floor: { width: 70, align: "right" as const, color: colors.cyan },
  Ref: { width: 70, align: "right" as const, color: colors.yellow },
  Ask1_Qty: { width: 85, align: "right" as const, color: colors.increase },
  Ask1_Prc: { width: 70, align: "right" as const, color: colors.increase },
  Traded: { width: 70, align: "right" as const, color: colors.increase },
  Bid1_Prc: { width: 70, align: "right" as const, color: colors.increase },
  Bid1_Qty: { width: 85, align: "right" as const, color: colors.increase },
  F_Buy: { width: 80, align: "right" as const, color: colors.textSecondary },
  F_Sell: { width: 80, align: "right" as const, color: colors.textSecondary },
  F_Room: { width: 100, align: "right" as const, color: colors.textSecondary },
} as const;

export type EquityColumnKey = keyof typeof equityColumns;

export const columnWidths = {
  small: 55,
  medium: 78,
  large: 106,
} as const;
