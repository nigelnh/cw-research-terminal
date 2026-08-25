/**
 * Holiday Calendar table definition (2026 Vietnamese public holidays)
 */

import { TableBase } from "../core/table_base";
import { ColumnBase } from "../core/column_base";
import type { TableConfig } from "../core/types";
import { colors, tableConfig } from "@/design/tokens";

export interface HolidayRow {
  event: string;
  date: string;
}

export class HolidayTable extends TableBase<Record<string, unknown> & HolidayRow> {
  readonly config: TableConfig = {
    headerHeightPx: tableConfig.headerHeight,
    rowHeightPx: tableConfig.rowHeight,
    maxRows: 50,
    fontSize: tableConfig.fontSize,
    headerFontSize: tableConfig.headerFontSize,
  };

  private columns: ColumnBase<HolidayRow>[];

  constructor() {
    super();

    this.columns = [
      // 1. Event name
      new ColumnBase<HolidayRow>({
        key: "event",
        header: "Event",
        flex: 2.0,
        align: "left",
        color: colors.textSecondary,
        format: (v) => {
          if (!v) return "—";
          return String(v);
        },
      }),

      // 2. Date
      new ColumnBase<HolidayRow>({
        key: "date",
        header: "Date",
        flex: 1.0,
        align: "center",
        color: colors.textSecondary,
        format: (v) => {
          if (!v) return "—";
          const str = String(v);
          // Normalize various date formats to D/M/YYYY
          // Handles: "2026-01-01", "01/01/2026", "1/1/2026"
          if (str.includes("-")) {
            const parts = str.split("T")[0].split("-");
            if (parts.length === 3) {
              const [year, month, day] = parts;
              return `${parseInt(day, 10)}/${parseInt(month, 10)}/${year}`;
            }
          }
          return str;
        },
      }),
    ];
  }

  getColumns(): ColumnBase<HolidayRow>[] {
    return this.columns;
  }

  getRowKey(row: HolidayRow): string {
    return `${row.date}:${row.event}`;
  }

  setAllRowsData(_rows: HolidayRow[]): void {
    // Standard pass-through
  }
}

export const holidayTable = new HolidayTable();
