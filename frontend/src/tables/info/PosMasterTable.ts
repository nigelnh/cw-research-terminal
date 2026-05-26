/**
 * pos_master table implementation aligned with spreadsheet specifications
 */

import { TableBase } from "../core/TableBase";
import { ColumnBase } from "../core/ColumnBase";
import type { TableConfig } from "../core/types";
import { colors, tableConfig } from "@/design/tokens";
import { getPriceColor } from "@/tables/equity/utils";

export interface PosMasterRow {
  ticker: string;
  und_ticker: string;
  last_prc_t: number | null;
  last_prc_t_1: number | null;
  net_chg_pct: number | null;
  expiry: string | null;
  dte: number | null;
  tte_t: number | null;
  tte_t_1: number | null;
  strike_k: number | null;
  multiplier_m: number | null;
  cvr: string | null;
  spot_prc_s: number | null;
  hedge_v_t: number | null;
  hedge_v_t_1: number | null;
  rate: number | null;
  div_d: number | null; // Database only
  fund: string | null;
  balance_t_1: number | null;
  balance: number | null;
  sold_amt: number | null;
  sold_qty: number | null;
  sold_avg: number | null;
  bought_amt: number | null;
  bought_qty: number | null;
  bought_avg: number | null;
  theo_prc_t: number | null;
  theo_prc_t_1: number | null;
  delta_t: number | null;
  delta_lots_t: number | null;
  delta_cash_t: number | null;
  delta_cash_t_1: number | null;
  trd_delta_lots_t: number | null;
  trd_delta_cash_t: number | null;
  gamma_amt_pct_t: number | null;
  vega_pct_t: number | null;
  cash_vega_t: number | null;
  theta_t: number | null;
  cash_theta_t: number | null;
  trading_pnl_theo: number | null;
  position_pnl_theo: number | null;
  delta_pnl: number | null;
  gamma_pnl: number | null;
  theta_pnl: number | null;
  vega_pnl: number | null;
  unexplained_pnl: number | null;
  capital_cost: number | null;
  total_pnl_theo: number | null;
  total_pnl_mtm: number | null;
  position_pnl_mtm: number | null;
  trading_pnl_mtm: number | null;
  total_pnl_theo_cum: number | null;
  total_pnl_mtm_cum: number | null;
}

// Precision formatters for compliance with spreadsheet masks
const formatNum = (v: unknown, decimals: number = 2): string => {
  if (v === null || v === undefined || v === "") return "N/A";
  const num = typeof v === "number" ? v : parseFloat(String(v));
  if (isNaN(num)) return "N/A";
  return num.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
};

const formatDelta = (v: unknown): string => {
  // Delta Sensitivities require exactly 3-decimal mask (x.xxx)
  return formatNum(v, 3);
};

const formatLots = (v: unknown): string => {
  // Greeks Volatility and Lots require exactly 1-decimal mask (xxxxxxxx.x)
  return formatNum(v, 1);
};

const formatCash = (v: unknown): string => {
  // Cash Volumes require exactly 1-decimal mask (xxxxxxxxxxxxx.x)
  return formatNum(v, 1);
};

const formatInt = (v: unknown): string => {
  // Inventory balances must be formatted as whole signed integers (e.g. -150,000)
  if (v === null || v === undefined || v === "") return "N/A";
  const num = typeof v === "number" ? v : parseInt(String(v), 10);
  if (isNaN(num)) return "N/A";
  return num.toLocaleString();
};

const formatPct = (v: unknown, decimals: number = 2): string => {
  if (v === null || v === undefined || v === "") return "N/A";
  const num = typeof v === "number" ? v : parseFloat(String(v));
  if (isNaN(num)) return "N/A";
  return (num * 100).toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + "%";
};

export class PosMasterTable extends TableBase<Record<string, unknown> & PosMasterRow> {
  readonly config: TableConfig = {
    headerHeightPx: tableConfig.headerHeight,
    rowHeightPx: tableConfig.rowHeight,
    maxRows: 1000,
    fontSize: tableConfig.fontSize,
    headerFontSize: tableConfig.headerFontSize,
  };

  private columns: ColumnBase<PosMasterRow>[];

  constructor() {
    super();

    this.columns = [
      // 1. Ticker (Col 3)
      new ColumnBase<PosMasterRow>({
        key: "ticker",
        header: "Ticker",
        flex: 1.2,
        align: "left",
        color: colors.increase,
        sortArrowOnRight: true,
      }),

      // 2. Und_Ticker (Col 5)
      new ColumnBase<PosMasterRow>({
        key: "und_ticker",
        header: "Und_Ticker",
        flex: 1,
        align: "left",
        color: colors.increase,
      }),

      // 3. LastPrc(T) — live realtime traded price of the CW symbol
      // Color: green if above Ref (last_prc_t_1), red if below, yellow if equal, purple/cyan at limits
      // Flash: up/down driven by posMasterChanges in App.tsx
      new ColumnBase<PosMasterRow>({
        key: "last_prc_t",
        header: "LastPrc(T)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v),
        color: (row: PosMasterRow) => {
          const prc   = row.last_prc_t  !== null && row.last_prc_t  !== undefined ? parseFloat(String(row.last_prc_t))  : 0;
          const ref   = row.last_prc_t_1 !== null && row.last_prc_t_1 !== undefined ? parseFloat(String(row.last_prc_t_1)) : 0;
          // CW warrants don't have KB Ceil/Floor, so use 0 — only green/yellow/red logic applies
          if (prc === 0) return colors.textSecondary;
          return getPriceColor(prc, ref, 0, 0);
        },
      }),

      // 4. LastPrc(T-1) — yesterday's reference/closing price from KB API (Ref field)
      // Shown in a neutral informational color — it's the baseline, never flashes
      new ColumnBase<PosMasterRow>({
        key: "last_prc_t_1",
        header: "LastPrc(T-1)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.volData,
      }),

      // 5. Net_Chg(%) (Col 10)
      new ColumnBase<PosMasterRow>({
        key: "net_chg_pct",
        header: "Net_Chg(%)",
        flex: 1.2,
        align: "right",
        format: (v) => formatPct(v),
        color: colors.increase,
      }),

      // 6. Expiry (Col 11)
      new ColumnBase<PosMasterRow>({
        key: "expiry",
        header: "Expiry",
        flex: 1.3,
        align: "center",
        format: (v) => {
          if (!v) return "N/A";
          const dateStr = String(v);
          if (dateStr.includes("T")) {
            const d = new Date(dateStr);
            // Shift +7 hours to get true Vietnam local calendar date
            const local = new Date(d.getTime() + 7 * 60 * 60 * 1000);
            const y = local.getUTCFullYear();
            const m = String(local.getUTCMonth() + 1).padStart(2, "0");
            const dy = String(local.getUTCDate()).padStart(2, "0");
            return `${y}-${m}-${dy}`;
          }
          return dateStr;
        },
        color: colors.increase,
      }),

      // 7. DTE (Col 12)
      new ColumnBase<PosMasterRow>({
        key: "dte",
        header: "DTE",
        flex: 0.8,
        align: "right",
        format: (v) => {
          if (v === null || v === undefined || v === "") return "N/A";
          const num = typeof v === "number" ? v : parseFloat(String(v));
          if (isNaN(num)) return "N/A";
          return num.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 2 });
        },
        color: colors.increase,
      }),

      // 8. TTE(t) (Col 13)
      new ColumnBase<PosMasterRow>({
        key: "tte_t",
        header: "TTE(t)",
        flex: 1.1,
        align: "right",
        format: (v) => formatNum(v, 6),
        color: colors.increase,
      }),

      // 9. TTE(t-1) (Col 14)
      new ColumnBase<PosMasterRow>({
        key: "tte_t_1",
        header: "TTE(t-1)",
        flex: 1.1,
        align: "right",
        format: (v) => formatNum(v, 6),
        color: colors.increase,
      }),

      // 10. Strike(K) (Col 15)
      new ColumnBase<PosMasterRow>({
        key: "strike_k",
        header: "Strike(K)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.increase,
      }),

      // 11. Multiplier(M) (Col 17)
      new ColumnBase<PosMasterRow>({
        key: "multiplier_m",
        header: "Multiplier(M)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v, 4),
        color: colors.increase,
      }),

      // 12. CVR (Col 18)
      new ColumnBase<PosMasterRow>({
        key: "cvr",
        header: "CVR",
        flex: 0.9,
        align: "center",
        format: (v) => v ? String(v) : "N/A",
        color: colors.increase,
      }),

      // 13. Spot_Prc(S) — live realtime traded price of the UNDERLYING stock
      // Color: uses getPriceColor relative to the underlying's Ref/Ceil/Floor from KB RT API
      // Flash: up/down driven by posMasterChanges in App.tsx
      new ColumnBase<PosMasterRow>({
        key: "spot_prc_s",
        header: "Spot_Prc(S)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v),
        color: (row: PosMasterRow, getRow?: (symbol: string) => any) => {
          const spotPrc = row.spot_prc_s !== null && row.spot_prc_s !== undefined
            ? parseFloat(String(row.spot_prc_s)) : 0;
          if (spotPrc === 0) return colors.textSecondary;
          // Look up the live underlying equity row for its Ref/Ceil/Floor
          if (getRow && row.und_ticker) {
            const undRow = getRow(row.und_ticker.toUpperCase());
            if (undRow) {
              return getPriceColor(spotPrc, undRow.Ref ?? 0, undRow.Ceil ?? 0, undRow.Floor ?? 0);
            }
          }
          return colors.increase;
        },
      }),

      // 14. HedgeV(T) (Col 20)
      new ColumnBase<PosMasterRow>({
        key: "hedge_v_t",
        header: "HedgeV(T)",
        flex: 1.1,
        align: "right",
        format: (v) => formatPct(v),
        color: colors.yellow,
      }),

      // 15. HedgeV(T-1) (Col 21)
      new ColumnBase<PosMasterRow>({
        key: "hedge_v_t_1",
        header: "HedgeV(T-1)",
        flex: 1.1,
        align: "right",
        format: (v) => formatPct(v),
        color: colors.yellow,
      }),

      // 16. Rate (Col 22)
      new ColumnBase<PosMasterRow>({
        key: "rate",
        header: "Rate",
        flex: 1,
        align: "right",
        format: (v) => formatPct(v),
        color: colors.yellow,
      }),

      // Note: Standalone Div(D) [Col 23] omitted from columns list as requested by "bỏ cột này"
      // to display it as a dot marker next to the ticker in TableView cell renderer instead.

      // 17. Fund (Col 24)
      new ColumnBase<PosMasterRow>({
        key: "fund",
        header: "Fund",
        flex: 1.2,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 18. Balance(T-1) (Col 25)
      new ColumnBase<PosMasterRow>({
        key: "balance_t_1",
        header: "Balance(T-1)",
        flex: 1.3,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 19. Balance (Col 26)
      new ColumnBase<PosMasterRow>({
        key: "balance",
        header: "Balance",
        flex: 1.3,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 20. Sold_Amt (Col 27)
      new ColumnBase<PosMasterRow>({
        key: "sold_amt",
        header: "Sold_Amt",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.yellow,
      }),

      // 21. Sold_Qty (Col 28)
      new ColumnBase<PosMasterRow>({
        key: "sold_qty",
        header: "Sold_Qty",
        flex: 1.3,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 22. Sold_Avg (Col 29)
      new ColumnBase<PosMasterRow>({
        key: "sold_avg",
        header: "Sold_Avg",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 23. Bought_Amt (Col 30)
      new ColumnBase<PosMasterRow>({
        key: "bought_amt",
        header: "Bought_Amt",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.yellow,
      }),

      // 24. Bought_Qty (Col 31)
      new ColumnBase<PosMasterRow>({
        key: "bought_qty",
        header: "Bought_Qty",
        flex: 1.3,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 25. Bought_Avg (Col 32)
      new ColumnBase<PosMasterRow>({
        key: "bought_avg",
        header: "Bought_Avg",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 26. TheoPrc(T) (Col 33)
      new ColumnBase<PosMasterRow>({
        key: "theo_prc_t",
        header: "TheoPrc(T)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v, 4),
        color: colors.increase,
      }),

      // 27. TheoPrc(T-1) (Col 34)
      new ColumnBase<PosMasterRow>({
        key: "theo_prc_t_1",
        header: "TheoPrc(T-1)",
        flex: 1.2,
        align: "right",
        format: (v) => formatNum(v, 4),
        color: colors.increase,
      }),

      // 28. Delta(T) (Col 35) - strictly 3 decimal places
      new ColumnBase<PosMasterRow>({
        key: "delta_t",
        header: "Delta(T)",
        flex: 1.2,
        align: "right",
        format: (v) => formatDelta(v),
        color: colors.increase,
      }),

      // 29. DeltaLots(T) (Col 36) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "delta_lots_t",
        header: "DeltaLots(T)",
        flex: 1.3,
        align: "right",
        format: (v) => formatLots(v),
        color: colors.purple,
      }),

      // 30. DeltaCash(T) (Col 37) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "delta_cash_t",
        header: "DeltaCash(T)",
        flex: 1.5,
        align: "right",
        format: (v) => formatCash(v),
        color: colors.purple,
      }),

      // 31. DeltaCash(T-1) (Col 38)
      new ColumnBase<PosMasterRow>({
        key: "delta_cash_t_1",
        header: "DeltaCash(T-1)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v, 1),
        color: colors.purple,
      }),

      // 32. TrdDeltaLots(T) (Col 39) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "trd_delta_lots_t",
        header: "TrdDeltaLots(T)",
        flex: 1.3,
        align: "right",
        format: (v) => formatLots(v),
        color: colors.purple,
      }),

      // 33. TrdDeltaCash(T) (Col 40) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "trd_delta_cash_t",
        header: "TrdDeltaCash(T)",
        flex: 1.5,
        align: "right",
        format: (v) => formatCash(v),
        color: colors.purple,
      }),

      // 34. %GammaAmt(T) (Col 41)
      new ColumnBase<PosMasterRow>({
        key: "gamma_amt_pct_t",
        header: "%GammaAmt(T)",
        flex: 1.4,
        align: "right",
        format: (v) => formatPct(v, 4),
        color: colors.increase,
      }),

      // 35. %Vega(T) (Col 42)
      new ColumnBase<PosMasterRow>({
        key: "vega_pct_t",
        header: "%Vega(T)",
        flex: 1.4,
        align: "right",
        format: (v) => formatPct(v, 4),
        color: colors.increase,
      }),

      // 36. CashVega(T) (Col 43)
      new ColumnBase<PosMasterRow>({
        key: "cash_vega_t",
        header: "CashVega(T)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 37. Theta(T) (Col 44)
      new ColumnBase<PosMasterRow>({
        key: "theta_t",
        header: "Theta(T)",
        flex: 1.4,
        align: "right",
        format: (v) => formatNum(v, 6),
        color: colors.increase,
      }),

      // 38. CashTheta(T) (Col 45)
      new ColumnBase<PosMasterRow>({
        key: "cash_theta_t",
        header: "CashTheta(T)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 39. TradingPnL(Theo) (Col 46)
      new ColumnBase<PosMasterRow>({
        key: "trading_pnl_theo",
        header: "TradingPnL(Theo)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 40. PositionPnL(Theo) (Col 47)
      new ColumnBase<PosMasterRow>({
        key: "position_pnl_theo",
        header: "PositionPnL(Theo)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 41. DeltaPnL (Col 48)
      new ColumnBase<PosMasterRow>({
        key: "delta_pnl",
        header: "DeltaPnL",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 42. GammaPnL (Col 49)
      new ColumnBase<PosMasterRow>({
        key: "gamma_pnl",
        header: "GammaPnL",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 43. ThetaPnL (Col 50)
      new ColumnBase<PosMasterRow>({
        key: "theta_pnl",
        header: "ThetaPnL",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 44. VegaPnL (Col 51)
      new ColumnBase<PosMasterRow>({
        key: "vega_pnl",
        header: "VegaPnL",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 45. UnexplainedPnL (Col 52)
      new ColumnBase<PosMasterRow>({
        key: "unexplained_pnl",
        header: "UnexplainedPnL",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 46. CapitalCost (Col 53)
      new ColumnBase<PosMasterRow>({
        key: "capital_cost",
        header: "CapitalCost",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.yellow,
      }),

      // 47. TotalPnL(Theo) - Daily (Col 54)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_theo",
        header: "TotalPnL(Theo)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 48. TotalPnL(MtM) - Daily (Col 55)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_mtm",
        header: "TotalPnL(MtM)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 49. PositionPnL(MtM) (Col 56)
      new ColumnBase<PosMasterRow>({
        key: "position_pnl_mtm",
        header: "PositionPnL(MtM)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 50. TradingPnL(MtM) (Col 57)
      new ColumnBase<PosMasterRow>({
        key: "trading_pnl_mtm",
        header: "TradingPnL(MtM)",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 51. TotalPnL(Theo) - Cumulative Annual (Col 58)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_theo_cum",
        header: "TotalPnL(Theo) Cum",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 52. TotalPnL(MtM) - Cumulative Annual (Col 59)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_mtm_cum",
        header: "TotalPnL(MtM) Cum",
        flex: 1.5,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),
    ];


  }

  getColumns(): ColumnBase<PosMasterRow>[] {
    return this.columns;
  }

  getRowKey(row: PosMasterRow): string {
    return row.ticker;
  }

  setAllRowsData(_rows: PosMasterRow[]): void {
    // Standard implementation
  }

  /**
   * Flash color override for PosMaster — mirrors StockTable.getFlashColor logic.
   * When a cell's value is 0/null/undefined, flash a muted color instead of green/red.
   */
  getFlashColor(
    row: PosMasterRow,
    colKey: string,
    _direction: "up" | "down",
    _getRow?: (symbol: string) => any
  ): string | undefined {
    if (colKey === "last_prc_t" || colKey === "spot_prc_s") {
      const val = colKey === "last_prc_t" ? row.last_prc_t : row.spot_prc_s;
      const num = val !== null && val !== undefined ? parseFloat(String(val)) : 0;
      if (num === 0) return colors.textSecondary;
    }
    return undefined; // use default green/red flash
  }
}

export const posMasterTable = new PosMasterTable();
