/**
 * Dividend Calendar table definition (VN30 stocks, rolling T±400 window, UI shows GDKHQDate today→+7)
 */

import { TableBase } from "../core/TableBase";
import { ColumnBase } from "../core/ColumnBase";
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
        widthPx: 72,
        align: "left",
        color: colors.yellow,
        sortArrowOnRight: true,
        format: (v) => {
          if (!v) return "—";
          return String(v).toUpperCase();
        },
      }),

      // 2. Company name
      new ColumnBase<DividendRow>({
        key: "name",
        header: "Name",
        widthPx: 90,
        align: "left",
        color: colors.textSecondary,
        format: (v) => {
          if (!v) return "—";
          return String(v);
        },
      }),

      // 2b. Event note / description (e.g. "Trả cổ tức năm 2025 bằng tiền, 1,000 đồng/CP")
      new ColumnBase<DividendRow>({
        key: "note",
        header: "Event",
        flex: 1,
        align: "left",
        color: colors.textPrimary,
        format: (v) => {
          if (!v) return "—";
          return String(v);
        },
      }),

      // 3. Ex-Dividend Date
      new ColumnBase<DividendRow>({
        key: "exDate",
        header: "Ex-Date",
        widthPx: 100,
        align: "center",
        color: colors.purple,
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

      // 4. Dividend document link (fileUrl) — rendered as a "↗ View" link in TableView
      new ColumnBase<DividendRow>({
        key: "fileUrl",
        header: "Document",
        widthPx: 84,
        align: "center",
        color: colors.increase,
        // Raw value is passed; the custom cell renderer in TableView handles links.
        // We mark non-empty values with a display label so TableView can detect it.
        format: (v) => {
          if (!v || String(v).trim() === "") return "—";
          // Return the URL prefixed with a sentinel so the TableView cell renderer
          // can detect and render it as a clickable link.
          return `__LINK__${String(v)}`;
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
