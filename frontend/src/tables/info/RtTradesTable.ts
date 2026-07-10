/**
 * rt_trades table implementation
 */

import { TableBase } from "../core/TableBase";
import { ColumnBase } from "../core/ColumnBase";
import type { TableConfig } from "../core/types";
import { colors, tableConfig } from "@/design/tokens";

export interface RtTradesRow {
  lastChange: string;
  acctNo: string;
  symbol: string;
  execType: string;
  execQtty: number;
  execPrice: number;
  quotePrice?: number;
  orStatusValue?: string;
  orStatus?: string;
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
    return `${under}`;
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
      // 1. Timestamp (lastChange)
      new ColumnBase<RtTradesRow>({
        key: "lastChange",
        header: "Timestamp",
        widthPx: 160,
        align: "center",
        format: (v) => {
          if (!v) return "";
          let str = String(v);
          if (/^\d+$/.test(str)) {
            str = new Date(Number(str)).toISOString();
          }
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

      // 2. Sub-account (acctNo)
      new ColumnBase<RtTradesRow>({
        key: "acctNo",
        header: "Sub-account",
        widthPx: 100,
        align: "center",
        color: colors.textSecondary,
      }),

      // 3. Symbol (symbol)
      new ColumnBase<RtTradesRow>({
        key: "symbol",
        header: "Symbol",
        widthPx: 90,
        align: "left",
        color: colors.textSecondary,
        sortArrowOnRight: true,
      }),

      // 4. Name (Derived)
      new ColumnBase<RtTradesRow>({
        key: "name",
        dataKey: "symbol" as any,
        header: "Name",
        widthPx: 130,
        align: "left",
        format: (v) => getSymbolName(String(v)),
        color: colors.textMuted,
      }),

      // 5. Product (Derived)
      new ColumnBase<RtTradesRow>({
        key: "product",
        dataKey: "symbol" as any,
        header: "Product",
        widthPx: 80,
        align: "center",
        format: (v) => String(v).length === 3 ? "Equity" : "Warrant",
        color: colors.textMuted,
      }),

      // 6. Underlying (Derived)
      new ColumnBase<RtTradesRow>({
        key: "underlying",
        dataKey: "symbol" as any,
        header: "Underlying",
        widthPx: 90,
        align: "center",
        format: (v) => getUnderlying(String(v)),
        color: colors.textSecondary,
      }),

      // 7. Call/Put (Derived)
      new ColumnBase<RtTradesRow>({
        key: "call_put",
        dataKey: "symbol" as any,
        header: "Call/Put",
        widthPx: 80,
        align: "center",
        format: (v) => String(v).length > 3 ? "Call" : "N/A",
        color: (row: RtTradesRow) => {
          const sym = String(row.symbol).toUpperCase();
          if (sym.length > 3) return colors.increase; // Warrants are calls (green)
          return colors.textMuted; // Equity is N/A
        },
      }),

      // 8. Buy/Sell (execType)
      new ColumnBase<RtTradesRow>({
        key: "execType",
        header: "Buy/Sell",
        widthPx: 80,
        align: "center",
        format: (v) => {
          if (!v) return "";
          const str = String(v).toUpperCase();
          if (str === "NB") return "Buy";
          if (str === "NS") return "Sell";
          return str;
        },
        color: (row: RtTradesRow) => {
          const t = String(row.execType).toUpperCase();
          if (t === "NB") return colors.increase; // Buy (green)
          if (t === "NS") return colors.decrease; // Sell (red)
          return colors.textSecondary;
        },
      }),

      // 9. Quantity (execQtty)
      new ColumnBase<RtTradesRow>({
        key: "execQtty",
        header: "Quantity",
        widthPx: 90,
        align: "right",
        format: (v) => {
          if (v === null || v === undefined) return "";
          const num = typeof v === "number" ? v : parseInt(String(v), 10);
          return isNaN(num) ? "" : num.toLocaleString();
        },
        color: colors.textSecondary,
      }),

      // 10. Traded_Prc (execPrice)
      new ColumnBase<RtTradesRow>({
        key: "execPrice",
        header: "Traded_Prc",
        widthPx: 95,
        align: "right",
        format: (v, row) => {
          let num = typeof v === "number" ? v : parseFloat(String(v));
          if ((isNaN(num) || num === 0) && row) {
            const rawRow = row as any;
            if (rawRow.quotePrice !== undefined && rawRow.quotePrice !== null) {
              num = typeof rawRow.quotePrice === "number" ? rawRow.quotePrice : parseFloat(String(rawRow.quotePrice));
            }
          }
          if (isNaN(num) || num === 0) return "";
          return (num / 1000).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        },
        color: (row: RtTradesRow) => {
          const t = String(row.execType).toUpperCase();
          if (t === "NB") return colors.increase; // Buy-executed price in green
          if (t === "NS") return colors.decrease; // Sell-executed price in red
          return colors.textSecondary;
        },
      }),

      // 11. Status (orStatusValue)
      new ColumnBase<RtTradesRow>({
        key: "status",
        dataKey: "orStatusValue" as any,
        header: "Status",
        widthPx: 90,
        align: "center",
        format: (v, row) => {
          if (v === null || v === undefined) {
            const rawRow = row as any;
            if (rawRow && rawRow.orStatus) {
              const os = String(rawRow.orStatus).toLowerCase();
              if (os.includes("gửi")) return "Send";
              if (os.includes("hủy")) return "Canceled";
              return rawRow.orStatus;
            }
            return "";
          }
          const val = String(v).trim();
          if (val === "2") return "Send";
          if (val === "3") return "Canceled";

          const rawRow = row as any;
          if (rawRow && rawRow.orStatus) {
            const os = String(rawRow.orStatus).toLowerCase();
            if (os.includes("gửi")) return "Send";
            if (os.includes("hủy")) return "Canceled";
            return rawRow.orStatus;
          }
          return val;
        },
        color: (row: RtTradesRow) => {
          const v = String(row.orStatusValue || "");
          if (v === "2") return colors.increase; // Green for Send
          if (v === "3") return colors.decrease; // Red for Canceled
          return colors.textSecondary;
        },
      }),
    ];
  }

  getColumns(): ColumnBase<RtTradesRow>[] {
    return this.columns;
  }

  getRowKey(row: RtTradesRow): string {
    return `${row.lastChange}:${row.acctNo}:${row.symbol}:${row.execType}:${row.execPrice}:${row.execQtty}`;
  }

  setAllRowsData(_rows: RtTradesRow[]): void {
    // Standard implementation
  }
}

export const rtTradesTable = new RtTradesTable();
