/**
 * CW table implementation
 * Includes Vol_CW column
 */

import { TableBase } from "../core/TableBase";
import {
    ColumnBase,
    PriceColumn,
    QuantityColumn,
} from "../core/ColumnBase";
import type { TableConfig } from "../core/types";
import type { EquityRow } from "../equity/types";
import { colors, tableConfig } from "@/design/tokens";
import { getPriceColor } from "../equity/utils";

// Custom column for computed change value
class ChangeColumn extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        const traded = row.Traded || 0;
        if (traded === 0) return undefined;
        return traded - (row.Ref || 0);
    }

    format(v: unknown): string {
        if (v === undefined || v === null) return "";
        return Number(v).toFixed(2);
    }
}

// Custom column for computed change percent
class ChangePercentColumn extends ColumnBase<EquityRow> {
    getValue(row: EquityRow): unknown {
        const traded = row.Traded || 0;
        const ref = row.Ref || 0;
        if (traded === 0 || ref === 0) return undefined;
        return ((traded - ref) / ref * 100);
    }

    format(v: unknown): string {
        if (v === undefined || v === null) return "";
        return Number(v).toFixed(2) + "%";
    }
}

// Custom column for Vol_Bid1 (Vol3) - only show if Bid1_Prc > 0
class VolBid1Column extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Bid1_Prc || row.Bid1_Prc <= 0) return undefined;
        return row.Vol3;
    }

    format(v: unknown): string {
        if (v === undefined || v === null) return "";
        const num = Number(v);
        if (num === -1) return ""; // Not calculated yet, or no price
        if (num === -2) return "NaN"; // Calculation error (sentinel from backend)
        return num.toFixed(2);
    }
}

// Custom column for Vol_Traded (Vol2) - only show if there is trading activity
class VolTradedColumn extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Traded || row.Traded <= 0) return undefined;
        return row.Vol2;
    }

    format(v: unknown): string {
        if (v === undefined || v === null) return "";
        const num = Number(v);
        if (num === -1) return ""; // Not calculated yet, or no price
        if (num === -2) return "NaN"; // Calculation error (sentinel from backend)
        return num.toFixed(2);
    }
}

class TradedPrcColumn extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Traded || row.Traded <= 0) return undefined;
        return row.Traded;
    }
}

// Custom column for Traded Quantity - only show if there is trading activity
class TradedQtyColumn extends QuantityColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Traded || row.Traded <= 0) return undefined;
        return row.Traded_Qty ?? 0;
    }
}

// Custom column for Vol_Ask1 (Vol1) - only show if Ask1_Prc > 0
class VolAsk1Column extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Ask1_Prc || row.Ask1_Prc <= 0) return undefined;
        return row.Vol1;
    }

    format(v: unknown): string {
        if (v === undefined || v === null) return "";
        const num = Number(v);
        if (num === -1) return ""; // Not calculated yet, or no price
        if (num === -2) return "NaN"; // Calculation error (sentinel from backend)
        return num.toFixed(2);
    }
}

// Bid1_Prc column - only show if > 0
class Bid1PrcColumn extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Bid1_Prc || row.Bid1_Prc <= 0) return undefined;
        return row.Bid1_Prc;
    }
}

// Bid1_Qty column - only show if corresponding price > 0
class Bid1QtyColumn extends QuantityColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Bid1_Prc || row.Bid1_Prc <= 0) return undefined;
        return row.Bid1_Qty ?? 0;
    }
}

// Ask1_Prc column - only show if > 0
class Ask1PrcColumn extends PriceColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Ask1_Prc || row.Ask1_Prc <= 0) return undefined;
        return row.Ask1_Prc;
    }
}

// Ask1_Qty column - only show if corresponding price > 0
class Ask1QtyColumn extends QuantityColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Ask1_Prc || row.Ask1_Prc <= 0) return undefined;
        return row.Ask1_Qty ?? 0;
    }
}

// Custom column for date sorting
class DateColumn<T> extends ColumnBase<T> {
    getValue(row: T): unknown {
        const v = row[this.key as keyof T];
        if (!v) return undefined;
        const d = new Date(v as string);
        return isNaN(d.getTime()) ? v : d.getTime();
    }
}

// Custom column for Spread calculation
class SpreadColumn extends ColumnBase<EquityRow> {
    getValue(row: EquityRow): unknown {
        if (!row.Ask1_Prc || !row.Bid1_Prc || row.Bid1_Prc === 0) return undefined;
        return ((row.Ask1_Prc - row.Bid1_Prc) / row.Bid1_Prc) * 100;
    }

    format(v: unknown): string {
        if (v === undefined || v === null) return "";
        const num = Number(v);
        if (num === 0) return "";
        return num.toFixed(2);
    }

    getColor(row: EquityRow): string {
        const spread = this.getValue(row);
        if (spread !== undefined && Math.round(Number(spread) * 100) / 100 >= 5) {
            return "#FFFFFF";
        }
        return super.getColor(row);
    }

    getBgColor(row: EquityRow): string | undefined {
        const spread = this.getValue(row);
        if (spread !== undefined && Math.round(Number(spread) * 100) / 100 >= 5) {
            return colors.decrease;
        }
        return super.getBgColor(row);
    }
}

// Total Vol column - only show if > 0
class TotalVolColumn extends QuantityColumn<EquityRow> {
    getValue(row: EquityRow): unknown {
        return row.Total_Vol;
    }
}

export class CWTable extends TableBase<Record<string, unknown> & EquityRow> {
    readonly config: TableConfig = {
        headerHeightPx: tableConfig.headerHeight,
        rowHeightPx: tableConfig.rowHeight,
        maxRows: 1000,
        fontSize: tableConfig.fontSize,
        headerFontSize: tableConfig.headerFontSize,
    };

    private columns: ColumnBase<EquityRow>[];
    private columnMap: Map<string, ColumnBase<EquityRow>> = new Map();
    private underlyingMap: Map<string, EquityRow> = new Map();

    constructor() {
        super();

        this.columns = [
            // Symbol
            new ColumnBase<EquityRow>({
                key: "Symbol",
                header: "Symbol",
                flex: 1.5,
                align: "left",
                color: (row: EquityRow) => this.getCWPriceColor(row.Traded, row.Ref, row.Ceil, row.Floor),
                sortArrowOnRight: true,
            }),

            // Issuer
            new ColumnBase<EquityRow>({
                key: "Issuer",
                header: "Issuer",
                flex: 1,
                align: "left",
                semanticColor: colors.volData,
                sortArrowOnRight: true,
            }),

            // Last Trading Date
            new DateColumn<EquityRow>({
                key: "LastTradingDate",
                header: "LTD",
                flex: 1.5,
                align: "left",
                semanticColor: colors.volData,
                sortArrowOnRight: true,
                format: (v) => {
                    if (!v) return "";
                    const d = typeof v === "number" ? new Date(v) : new Date(v as string);
                    if (isNaN(d.getTime())) return v as string;
                    const day = String(d.getDate()).padStart(2, '0');
                    const month = String(d.getMonth() + 1).padStart(2, '0');
                    const year = d.getFullYear();
                    return `${day}/${month}/${year}`;
                }
            }),

            // Maturity Date
            // new ColumnBase<EquityRow>({
            //     key: "MaturityDate",
            //     header: "Maturity Date",
            //     flex: 2,
            //     align: "left",
            //     semanticColor: colors.volData,
            //     format: (v) => {
            //         if (!v) return "";
            //         const d = new Date(v as string);
            //         if (isNaN(d.getTime())) return v as string;
            //         const day = String(d.getDate()).padStart(2, '0');
            //         const month = String(d.getMonth() + 1).padStart(2, '0');
            //         const year = d.getFullYear();
            //         return `${day}/${month}/${year}`;
            //     }
            // }),

            // Price columns
            new PriceColumn<EquityRow>({
                key: "Ceil",
                header: "Ceil",
                flex: 1,
                align: "right",
                semanticColor: colors.purple,
            }),
            new PriceColumn<EquityRow>({
                key: "Floor",
                header: "Floor",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Floor, row.Ref, row.Ceil, row.Floor),
            }),
            new PriceColumn<EquityRow>({
                key: "Ref",
                header: "Ref",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Ref, row.Ref, row.Ceil, row.Floor),
            }),

            // Vol3 -> Rebranded as Vol_Bid1 (only show if Bid1_Prc > 0)
            new VolBid1Column({
                key: "Vol3",
                header: "Vol_Bid1",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
            }),
            // Bid side
            new Bid1PrcColumn({
                key: "Bid1_Prc",
                header: "Bid1_Prc",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Bid1_Prc, row.Ref, row.Ceil, row.Floor),
            }),
            new Bid1QtyColumn({
                key: "Bid1_Qty",
                header: "Bid1_Qty",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Bid1_Prc, row.Ref, row.Ceil, row.Floor),
            }),

            // Vol2 -> Rebranded as Vol_Traded (only show if Traded > 0)
            new VolTradedColumn({
                key: "Vol2",
                header: "Vol_Traded",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
            }),
            // Traded price
            new TradedPrcColumn({
                key: "Traded",
                header: "Traded_Prc",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Traded, row.Ref, row.Ceil, row.Floor),
            }),
            new TradedQtyColumn({
                key: "Traded_Qty",
                header: "Quantity",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Traded, row.Ref, row.Ceil, row.Floor),
            }),
            // +/-
            new ChangeColumn({
                key: "Change" as any,
                header: "+/-",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => {
                    const traded = row.Traded ?? 0;
                    const ref = row.Ref ?? 0;
                    const floor = row.Floor ?? 0;
                    // If ref and floor are both 0.01, treat 0.01 as reference (yellow)
                    if (ref === 0.01 && floor === 0.01 && traded === 0.01) return colors.yellow;
                    if (traded === floor && traded !== 0) return colors.cyan;
                    const change = traded - ref;
                    if (change > 0) return colors.increase;
                    if (change < 0) return colors.decrease;
                    return colors.yellow;
                },
            }),
            // +/- (%)
            new ChangePercentColumn({
                key: "ChangePercent" as any,
                header: "+/-(%)",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => {
                    const traded = row.Traded ?? 0;
                    const ref = row.Ref ?? 0;
                    const floor = row.Floor ?? 0;
                    // If ref and floor are both 0.01, treat 0.01 as reference (yellow)
                    if (ref === 0.01 && floor === 0.01 && traded === 0.01) return colors.yellow;
                    if (traded === floor && traded !== 0) return colors.cyan;
                    const change = traded - ref;
                    if (change > 0) return colors.increase;
                    if (change < 0) return colors.decrease;
                    return colors.yellow;
                },
            }),

            new SpreadColumn({
                key: "Spread" as any,
                header: "Spread(%)",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
            }),

            // Vol1 -> Rebranded as Vol_Ask1 (only show if Ask1_Prc > 0)
            new VolAsk1Column({
                key: "Vol1",
                header: "Vol_Ask1",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
            }),
            // Ask side
            new Ask1PrcColumn({
                key: "Ask1_Prc",
                header: "Ask1_Prc",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Ask1_Prc, row.Ref, row.Ceil, row.Floor),
            }),

            new Ask1QtyColumn({
                key: "Ask1_Qty",
                header: "Ask1_Qty",
                flex: 1,
                align: "right",
                color: (row: EquityRow) => this.getCWPriceColor(row.Ask1_Prc, row.Ref, row.Ceil, row.Floor),
            }),

            // Total Vol (SSI index 54)
            new TotalVolColumn({
                key: "Total_Vol",
                header: "Total_Vol",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
            }),

            // Underlying Symbol
            new ColumnBase<EquityRow>({
                key: "Under_Symbol",
                header: "Under_Sym",
                flex: 1,
                align: "right",
                color: (row, getRow) => this.getUnderlyingColor(row, getRow),
                colorDependencies: ["Under_Prc"],
            }),

            // Underlying Price
            new PriceColumn<EquityRow>({
                key: "Under_Prc",
                header: "Under_Prc",
                flex: 1,
                align: "right",
                color: (row, getRow) => this.getUnderlyingColor(row, getRow),
            }),

            // Strike Price
            new PriceColumn<EquityRow>({
                key: "Strike_Prc",
                header: "Strike_Prc",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
                format: (v) => {
                    if (!v || v === 0) return "";
                    return (Number(v) / 1000).toFixed(3);
                }
            }),

            // Ratio
            new ColumnBase<EquityRow>({
                key: "Ratio",
                header: "Ratio",
                flex: 1,
                align: "right",
                semanticColor: colors.volData,
            }),

            // Listed Volume (Database)
            new QuantityColumn<EquityRow>({
                key: "Listed_Vol",
                header: "Listed_Vol",
                flex: 1.5,
                align: "right",
                semanticColor: colors.volData,
            }),
        ];

        // Cache columns for faster lookup during render/flash
        this.columns.forEach(col => this.columnMap.set(col.key, col));
    }

    // Helper to get color with specialized CW logic (handling 0.01 floor/ref case)
    private getCWPriceColor(price: number | null, ref: number | null, ceil: number | null, floor: number | null): string {
        const p = price ?? 0;
        const r = ref ?? 0;
        const c = ceil ?? 0;
        const f = floor ?? 0;

        if (p === 0) return colors.textSecondary;
        // If ref and floor are both 0.01, treat 0.01 as reference (yellow) instead of floor (cyan)
        if (r === 0.01 && f === 0.01 && p === 0.01) return colors.yellow;
        return getPriceColor(p, r, c, f);
    }

    getUnderlyingColor(row: EquityRow, getRow?: (symbol: string) => EquityRow | undefined): string {
        const underPrc = row.Under_Prc || 0;
        const underSymbolKey = row.Under_Symbol;
        if (underPrc === 0 || !underSymbolKey) return colors.textSecondary;

        // Optimized time calculation for market hours (Vietnam is UTC+7)
        const now = new Date();
        const utcMinutes = now.getUTCHours() * 60 + now.getUTCMinutes();
        const vnMinutes = (utcMinutes + 7 * 60) % (24 * 60);

        if (vnMinutes < (9 * 60 + 15)) {
            return colors.yellow;
        }

        // Use the injected lookup function if available, otherwise fallback to internal map
        const underlyingSymbol = getRow ? getRow(underSymbolKey) : this.underlyingMap.get(underSymbolKey);

        if (!underlyingSymbol || !underlyingSymbol.Ref) {
            return colors.yellow;
        }

        const underRef = underlyingSymbol.Ref;
        const underCeil = underlyingSymbol.Ceil || 0;
        const underFloor = underlyingSymbol.Floor || 0;

        if (underPrc === underCeil) return colors.purple;
        if (underPrc === underFloor) return colors.cyan;
        if (underPrc > underRef) return colors.increase;
        if (underPrc < underRef) return colors.decrease;
        return colors.yellow;
    }

    getColumns(): ColumnBase<EquityRow>[] {
        return this.columns;
    }

    getRowKey(row: EquityRow): string {
        return row.Symbol;
    }

    // Method to update underlying map before rendering
    setAllRowsData(rows: EquityRow[]): void {
        this.underlyingMap.clear();
        for (const r of rows) {
            // Underlyings have short symbols (<= 3 chars)
            if (r.Symbol && r.Symbol.length <= 3) {
                this.underlyingMap.set(r.Symbol, r);
            }
        }
    }

    // Reuse flash logic
    getFlashColor(
        row: EquityRow,
        colKey: string,
        _direction: "up" | "down",
        getRow?: (symbol: string) => EquityRow | undefined
    ): string | undefined {
        // Special logic for empty/canceled orders
        const bid1Prc = row.Bid1_Prc ?? 0;
        const ask1Prc = row.Ask1_Prc ?? 0;
        const traded = row.Traded ?? 0;

        if (
            ((colKey === "Bid1_Prc" || colKey === "Bid1_Qty" || colKey === "Vol3" || colKey === "Spread") && bid1Prc === 0) ||
            ((colKey === "Ask1_Prc" || colKey === "Ask1_Qty" || colKey === "Vol1" || colKey === "Spread") && ask1Prc === 0) ||
            ((colKey === "Traded" || colKey === "Traded_Qty" || colKey === "Vol2" || colKey === "Change" || colKey === "ChangePercent") && traded === 0)
        ) {
            return colors.textSecondary;
        }

        if (colKey === "Vol1" || colKey === "Vol2" || colKey === "Vol3") {
            return colors.textMuted;
        }

        // Special logic for Spread column: flash red if spread >= 5, grey otherwise
        if (colKey === "Spread") {
            const ask = row.Ask1_Prc || 0;
            const bid = row.Bid1_Prc || 0;
            if (bid !== 0) {
                const spread = ((ask - bid) / bid) * 100;
                if (Math.round(spread * 100) / 100 >= 5) {
                    return colors.decrease;
                } else {
                    return colors.textMuted; // "default grey"
                }
            }
        }

        // Find the column by key and use its own color logic
        const col = this.columnMap.get(colKey);
        if (col) {
            const color = col.getColor(row, getRow);
            if (color === colors.cyan) {
                return colors.blue;
            }
            return color;
        }

        return undefined;
    }
}

export const cwTable = new CWTable();
