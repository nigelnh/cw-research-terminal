/**
 * rt_trades table implementation
 */

import { TableBase } from "../core/TableBase";
import { ColumnBase } from "../core/ColumnBase";
import type { TableConfig } from "../core/types";
import { colors, tableConfig } from "@/design/tokens";

export interface RtTradesRow {
  datetime: string;
  symbol: string;
  sub_acc: string;
  type: string;
  price: number;
  volume: number;
  matched_prc: number | null;
  matched_vol: number | null;
  order_type: string | null;
}

// Helper to derive name
const getSymbolName = (symbol: string): string => {
  const sym = symbol.toUpperCase();
  if (sym === "HPG") return "Hoa Phat Group";
  if (sym === "FPT") return "FPT Corporation";
  if (sym === "VHM") return "Vinhomes JSC";
  if (sym === "VIC") return "Vingroup JSC";
  if (sym === "MWG") return "Mobile World Group";

  if (sym.startsWith("C") && sym.length >= 8) {
    const under = sym.substring(1, 4);
    return `Covered Warrant ${under}`;
  }
  return sym;
};

// Helper to derive underlying
const getUnderlying = (symbol: string): string => {
  const sym = symbol.toUpperCase();
  if (sym.length === 3) return sym;
  if (sym.startsWith("C") && sym.length >= 8) {
    return sym.substring(1, 4);
  }
  return sym;
};

export class RtTradesTable extends TableBase<Record<string, unknown> & RtTradesRow> {
  readonly config: TableConfig = {
    headerHeightPx: tableConfig.headerHeight,
    rowHeightPx: tableConfig.rowHeight,
    maxRows: 1000,
    fontSize: tableConfig.fontSize,
    headerFontSize: tableConfig.headerFontSize,
  };

  private columns: ColumnBase<RtTradesRow>[];

  constructor() {
    super();

    this.columns = [
      // 1. Timestamp (datetime)
      new ColumnBase<RtTradesRow>({
        key: "datetime",
        header: "Timestamp",
        flex: 1.5,
        align: "center",
        format: (v) => {
          if (!v) return "N/A";
          // Format standard PostgreSQL timestamp like "2026-05-20T02:15:32.000Z" or similar
          const str = String(v);
          if (str.includes("T")) {
            const parts = str.split("T");
            const date = parts[0];
            const time = parts[1].split(".")[0];
            return `${date} ${time}`;
          }
          return str;
        },
        color: colors.textMuted,
      }),

      // 2. Symbol
      new ColumnBase<RtTradesRow>({
        key: "symbol",
        header: "Symbol",
        flex: 0.9,
        align: "left",
        color: colors.textSecondary,
        sortArrowOnRight: true,
      }),

      // 3. Name (Derived)
      new ColumnBase<RtTradesRow>({
        key: "name",
        dataKey: "symbol" as any,
        header: "Name",
        flex: 1.5,
        align: "left",
        format: (v) => getSymbolName(String(v)),
        color: colors.textMuted,
      }),

      // 4. Product (Derived)
      new ColumnBase<RtTradesRow>({
        key: "product",
        dataKey: "symbol" as any,
        header: "Product",
        flex: 0.8,
        align: "center",
        format: (v) => String(v).length === 3 ? "Equity" : "Warrant",
        color: colors.textMuted,
      }),

      // 5. Underlying (Derived)
      new ColumnBase<RtTradesRow>({
        key: "underlying",
        dataKey: "symbol" as any,
        header: "Underlying",
        flex: 0.9,
        align: "center",
        format: (v) => getUnderlying(String(v)),
        color: colors.textSecondary,
      }),

      // 6. Call/Put (Derived)
      new ColumnBase<RtTradesRow>({
        key: "call_put",
        dataKey: "symbol" as any,
        header: "Call/Put",
        flex: 0.8,
        align: "center",
        format: (v) => String(v).length > 3 ? "Call" : "N/A",
        color: (row: RtTradesRow) => {
          const sym = String(row.symbol).toUpperCase();
          if (sym.length > 3) return colors.increase; // Warrants are calls (green)
          return colors.textMuted; // Equity is N/A
        },
      }),

      // 7. Buy/Sell (type)
      new ColumnBase<RtTradesRow>({
        key: "type",
        header: "Buy/Sell",
        flex: 0.8,
        align: "center",
        format: (v) => {
          if (!v) return "";
          const str = String(v);
          return str.charAt(0).toUpperCase() + str.slice(1).toLowerCase();
        },
        color: (row: RtTradesRow) => {
          const t = String(row.type).toLowerCase();
          if (t.startsWith("b")) return colors.increase; // Buy (green)
          if (t.startsWith("s")) return colors.decrease; // Sell (red)
          return colors.textSecondary;
        },
      }),

      // 8. Quantity (volume)
      new ColumnBase<RtTradesRow>({
        key: "volume",
        header: "Quantity",
        flex: 1.0,
        align: "right",
        format: (v) => {
          if (v === null || v === undefined) return "0";
          const num = typeof v === "number" ? v : parseInt(String(v), 10);
          return isNaN(num) ? "0" : num.toLocaleString();
        },
        color: colors.textSecondary,
      }),

      // 9. Traded_Prc (price)
      new ColumnBase<RtTradesRow>({
        key: "price",
        header: "Traded_Prc",
        flex: 1.0,
        align: "right",
        format: (v) => {
          if (v === null || v === undefined) return "N/A";
          const num = typeof v === "number" ? v : parseFloat(String(v));
          return isNaN(num) ? "N/A" : num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        },
        color: (row: RtTradesRow) => {
          const t = String(row.type).toLowerCase();
          if (t.startsWith("b")) return colors.increase; // Buy-executed price in green
          if (t.startsWith("s")) return colors.decrease; // Sell-executed price in red
          return colors.textSecondary;
        },
      }),
    ];
  }

  getColumns(): ColumnBase<RtTradesRow>[] {
    return this.columns;
  }

  getRowKey(row: RtTradesRow): string {
    // Generate a unique row key combining properties since there's a composite PK
    return `${row.datetime}:${row.symbol}:${row.type}:${row.price}:${row.volume}`;
  }

  setAllRowsData(_rows: RtTradesRow[]): void {
    // Standard implementation
  }
}

export const rtTradesTable = new RtTradesTable();
