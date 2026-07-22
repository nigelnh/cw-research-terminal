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



// Helper to derive underlying
const getUnderlying = (symbol: string): string => {
  const sym = symbol.toUpperCase();
  if (sym.length === 3) return sym;
  if (sym.startsWith("C") && sym.length >= 8) {
    return sym.substring(1, 4);
  }
  return sym;
};

// Status translation map
const STATUS_MAP: Record<string, string> = {
  "0": "Rejected",
  "1": "Open",
  "2": "Sent",
  "3": "Cancelled",
  "A": "Amending",
  "4": "Matched",
  "5": "Expired",
  "C": "Cancelling",
  "6": "Rejected",
  "7": "Success",
  "8": "Pending Send",
  "9": "Pending Approval",
  "10": "Amended",
  "11": "Sending",
  "12": "Matched",
  "13": "Pending Confirmation",
  "P": "Pending",
  "E": "Expired",
  "R": "Cancelled",
  "W": "Pending Margin",
};

// Helper to translate status
const getStatusText = (v: unknown, orStatus?: string): string => {
  if (v !== null && v !== undefined) {
    const val = String(v).trim().toUpperCase();
    if (STATUS_MAP[val]) return STATUS_MAP[val];
  }
  if (orStatus) {
    const text = String(orStatus).trim().toLowerCase();
    if (text.includes("từ chối")) return "Rejected";
    if (text.includes("mở")) return "Open";
    if (text.includes("đã gửi")) return "Sent";
    if (text.includes("Đang gửi")) return "Sending";
    if (text.includes("đã hủy")) return "Cancelled";
    if (text.includes("đang hủy")) return "Cancelling";
    if (text.includes("hủy bỏ")) return "Cancelled";
    if (text.includes("đang sửa")) return "Amending";
    if (text.includes("đã khớp")) return "Matched";
    if (text.includes("khớp hết")) return "Matched";
    if (text.includes("hết hiệu lực")) return "Expired";
    if (text.includes("hết hạn")) return "Expired";
    if (text.includes("thành công")) return "Success";
    if (text.includes("chờ gửi")) return "Pending Send";
    if (text.includes("chờ duyệt")) return "Pending Approval";
    if (text.includes("đã sửa")) return "Amended";
    if (text.includes("chờ xác nhận")) return "Pending Confirmation";
    if (text.includes("chờ xử lý")) return "Pending";
    if (text.includes("chờ ký quỹ")) return "Pending Margin";

    const textUpper = text.toUpperCase();
    if (STATUS_MAP[textUpper]) return STATUS_MAP[textUpper];
    return orStatus;
  }
  return v !== null && v !== undefined ? String(v) : "";
};

// Helper to get color based on status text or code
const getStatusColor = (status: string): string => {
  switch (status) {
    case "Sent":
    case "Matched":
    case "Success":
      return colors.increase;
    case "Cancelled":
    case "Rejected":
    case "Expired":
      return colors.decrease;
    default:
      return colors.textSecondary;
  }
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
          const rawRow = row as any;
          const orStatus = rawRow ? rawRow.orStatus : undefined;
          return getStatusText(v, orStatus);
        },
        color: (row: RtTradesRow) => {
          const rawRow = row as any;
          const orStatus = rawRow ? rawRow.orStatus : undefined;
          const statusText = getStatusText(row.orStatusValue, orStatus);
          return getStatusColor(statusText);
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
