/**
 * Dividend Calendar table definition (VN30 stocks, rolling T±400 window, UI shows GDKHQDate today→+7)
 */

import { TableBase } from "../core/table_base";
import { ColumnBase } from "../core/column_base";
import type { TableConfig } from "../core/types";
import { colors, tableConfig } from "@/design/tokens";

export interface DividendRow {
  symbol: string;
  name: string;
  exDate: string;
  note: string;
  fileUrl: string;
}

export class DividendTable extends TableBase<Record<string, unknown> & DividendRow> {
  readonly config: TableConfig = {
    headerHeightPx: tableConfig.headerHeight,
    rowHeightPx: tableConfig.rowHeight,
    maxRows: 100,
    fontSize: tableConfig.fontSize,
    headerFontSize: tableConfig.headerFontSize,
  };

  private columns: ColumnBase<DividendRow>[];

  constructor() {
    super();

    this.columns = [
      // 1. Symbol (ticker)
      new ColumnBase<DividendRow>({
        key: "symbol",
        header: "Symbol",
        flex: 0.1,
        align: "left",
        color: colors.textSecondary,
        sortArrowOnRight: true,
        format: (v) => {
          if (!v) return "—";
          return String(v).toUpperCase();
        },
      }),

      // 2b. Event note / description (e.g. "2025 cash dividend payment, 1,000 VND/share")
      new ColumnBase<DividendRow>({
        key: "note",
        header: "Event",
        flex: 3,
        align: "left",
        color: colors.textSecondary,
        format: (v) => {
          if (!v) return "—";
          return String(v);
        },
      }),

      // 3. Ex-Dividend Date
      new ColumnBase<DividendRow>({
        key: "exDate",
        header: "Ex-Date",
        flex: 0.2,
        align: "center",
        color: colors.textSecondary,
        format: (v) => {
          if (!v) return "—";
          const str = String(v);
          // Normalize ISO dates "2026-05-28" → "28/05/2026"
          if (str.includes("-")) {
            const parts = str.split("T")[0].split("-");
            if (parts.length === 3) {
              const [year, month, day] = parts;
              return `${day}/${month}/${year}`;
            }
          }
          return str;
        },
      }),

    ];
  }

  getColumns(): ColumnBase<DividendRow>[] {
    return this.columns;
  }

  getRowKey(row: DividendRow): string {
    // Include note to avoid collisions when two events share the same symbol+exDate
    return `${row.symbol}:${row.exDate}:${row.note}`;
  }

  setAllRowsData(_rows: DividendRow[]): void {
    // Standard pass-through
  }
}

export const dividendTable = new DividendTable();
