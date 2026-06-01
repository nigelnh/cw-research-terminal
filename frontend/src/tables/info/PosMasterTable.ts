/**
 * pos_master table implementation aligned with spreadsheet specifications
 */

import { TableBase } from "../core/TableBase";
import { ColumnBase } from "../core/ColumnBase";
import type { TableConfig } from "../core/types";
import { colors, tableConfig } from "@/design/tokens";
import { getPriceColor } from "@/tables/equity/utils";

/**
 * The four logical column groups for the PosMaster tabbed sub-view layout.
 * "all" is a special sentinel that returns every column (used for the
 * DisplayOption panel and any non-tabbed consumer).
 */
export type PosColumnGroup = "overview" | "summary" | "inventory" | "greeks" | "pnl" | "all";

/** Human-readable labels, accent colours, and column counts for the tab bar */
export const POS_GROUP_META: Record<Exclude<PosColumnGroup, "all">, { label: string; color: string; count: number }> = {
  overview:  { label: "Overview",  color: "#0ECB81", count: 52 },
  summary:   { label: "Summary",   color: "#FF9F1C", count: 13 },
  inventory: { label: "Inventory", color: "#FFD700", count: 11 },
  greeks:    { label: "Greeks",    color: "#C77DFF", count: 17 },
  pnl:       { label: "PnL",       color: "#C77DFF", count: 16 },
};

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

  activeGroup: PosColumnGroup = "overview";
  private columns: ColumnBase<PosMasterRow>[];

  constructor() {
    super();

    this.columns = [
      // 1. Ticker (Col 3)
      new ColumnBase<PosMasterRow>({
        key: "ticker",
        header: "Ticker",
        widthPx: 70,
        align: "left",
        color: (row: PosMasterRow) => {
          const prc   = row.last_prc_t  !== null && row.last_prc_t  !== undefined ? parseFloat(String(row.last_prc_t))  : 0;
          const ref   = row.last_prc_t_1 !== null && row.last_prc_t_1 !== undefined ? parseFloat(String(row.last_prc_t_1)) : 0;
          if (prc === 0) return colors.textSecondary;
          return getPriceColor(prc, ref, 0, 0);
        },
        sortArrowOnRight: true,
      }),

      // 2. Und_Ticker (Col 5)
      // Color: based on the underlying's own live Ref/Ceil/Floor (exactly like Equity table logic)
      new ColumnBase<PosMasterRow>({
        key: "und_ticker",
        header: "Und_Ticker",
        widthPx: 55,
        align: "left",
        color: (row: PosMasterRow, getRow?: (symbol: string) => any) => {
          const undRow = getRow ? getRow(row.und_ticker) : null;
          const spot  = undRow?.Traded ?? 0;
          if (!spot) return colors.textSecondary;
          const ref   = undRow?.Ref   ?? 0;
          const ceil  = undRow?.Ceil  ?? 0;
          const floor = undRow?.Floor ?? 0;
          return getPriceColor(spot, ref, ceil, floor);
        },
      }),

      // 3. LastPrc(T) — live realtime traded price of the CW symbol
      // Color: green if above Ref (last_prc_t_1), red if below, yellow if equal, purple/cyan at limits
      // Flash: up/down driven by posMasterChanges in App.tsx
      new ColumnBase<PosMasterRow>({
        key: "last_prc_t",
        header: "LastPrc(T)",
        widthPx: 70,
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
        widthPx: 70,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.volData,
      }),

      // 5. Net_Chg(%) (Col 10)
      new ColumnBase<PosMasterRow>({
        key: "net_chg_pct",
        header: "Net_Chg(%)",
        widthPx: 65,
        align: "right",
        format: (v) => formatPct(v),
        color: (row: PosMasterRow) => {
          const prc   = row.last_prc_t  !== null && row.last_prc_t  !== undefined ? parseFloat(String(row.last_prc_t))  : 0;
          const ref   = row.last_prc_t_1 !== null && row.last_prc_t_1 !== undefined ? parseFloat(String(row.last_prc_t_1)) : 0;
          if (prc === 0) return colors.textSecondary;
          return getPriceColor(prc, ref, 0, 0);
        },
      }),

      // 6. Expiry (Col 11)
      new ColumnBase<PosMasterRow>({
        key: "expiry",
        header: "Expiry",
        widthPx: 75,
        align: "center",
        format: (v) => {
          if (!v) return "N/A";
          const dateStr = String(v);
          let y = "";
          let m = "";
          let dy = "";
          if (dateStr.includes("T")) {
            const d = new Date(dateStr);
            // Shift +7 hours to get true Vietnam local calendar date
            const local = new Date(d.getTime() + 7 * 60 * 60 * 1000);
            y = String(local.getUTCFullYear());
            m = String(local.getUTCMonth() + 1).padStart(2, "0");
            dy = String(local.getUTCDate()).padStart(2, "0");
          } else {
            const parts = dateStr.split("-");
            if (parts.length === 3 && parts[0].length === 4) {
              [y, m, dy] = parts;
            } else {
              return dateStr;
            }
          }
          return `${dy}/${m}/${y}`;
        },
        color: colors.increase,
      }),

      // 7. DTE (Col 12)
      new ColumnBase<PosMasterRow>({
        key: "dte",
        header: "DTE",
        widthPx: 50,
        align: "right",
        format: (v) => {
          if (v === null || v === undefined || v === "") return "N/A";
          const num = typeof v === "number" ? v : parseFloat(String(v));
          if (isNaN(num)) return "N/A";
          return num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        },
        color: colors.increase,
      }),

      // 8. TTE(t) (Col 13)
      new ColumnBase<PosMasterRow>({
        key: "tte_t",
        header: "TTE(t)",
        widthPx: 75,
        align: "right",
        format: (v) => formatNum(v, 6),
        color: colors.increase,
      }),

      // 9. TTE(t-1) (Col 14)
      new ColumnBase<PosMasterRow>({
        key: "tte_t_1",
        header: "TTE(t-1)",
        widthPx: 75,
        align: "right",
        format: (v) => formatNum(v, 6),
        color: colors.increase,
      }),

      // 10. Strike(K) (Col 15)
      new ColumnBase<PosMasterRow>({
        key: "strike_k",
        header: "Strike(K)",
        widthPx: 70,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.increase,
      }),

      // 11. Multiplier(M) (Col 17)
      new ColumnBase<PosMasterRow>({
        key: "multiplier_m",
        header: "Multiplier(M)",
        widthPx: 65,
        align: "right",
        format: (v) => formatNum(v, 4),
        color: colors.increase,
      }),

      // 12. CVR (Col 18)
      new ColumnBase<PosMasterRow>({
        key: "cvr",
        header: "CVR",
        widthPx: 50,
        align: "center",
        format: (v) => v ? String(v) : "N/A",
        color: colors.increase,
      }),

      // 13. Spot_Prc(S) — live realtime traded price of the UNDERLYING stock
      // Color: based on the underlying's own live Ref/Ceil/Floor (exactly like Equity table logic)
      // Flash: up/down driven by posMasterChanges in App.tsx
      new ColumnBase<PosMasterRow>({
        key: "spot_prc_s",
        header: "Spot_Prc(S)",
        widthPx: 75,
        align: "right",
        format: (v) => formatNum(v),
        color: (row: PosMasterRow, getRow?: (symbol: string) => any) => {
          const spot = row.spot_prc_s !== null && row.spot_prc_s !== undefined
            ? parseFloat(String(row.spot_prc_s)) : 0;
          if (!spot) return colors.textSecondary;
          // Resolve the underlying's live equity row for its own Ref/Ceil/Floor
          const undRow = getRow ? getRow(row.und_ticker) : null;
          const ref  = undRow?.Ref  ?? 0;
          const ceil = undRow?.Ceil ?? 0;
          const floor = undRow?.Floor ?? 0;
          return getPriceColor(spot, ref, ceil, floor);
        },
      }),

      // 14. HedgeV(T) (Col 20)
      new ColumnBase<PosMasterRow>({
        key: "hedge_v_t",
        header: "HedgeV(T)",
        widthPx: 70,
        align: "right",
        format: (v) => formatPct(v),
        color: colors.yellow,
      }),

      // 15. HedgeV(T-1) (Col 21)
      new ColumnBase<PosMasterRow>({
        key: "hedge_v_t_1",
        header: "HedgeV(T-1)",
        widthPx: 70,
        align: "right",
        format: (v) => formatPct(v),
        color: colors.yellow,
      }),

      // 16. Rate (Col 22)
      new ColumnBase<PosMasterRow>({
        key: "rate",
        header: "Rate",
        widthPx: 50,
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
        widthPx: 60,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 18. Balance(T-1) (Col 25)
      new ColumnBase<PosMasterRow>({
        key: "balance_t_1",
        header: "Balance(T-1)",
        widthPx: 75,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 19. Balance (Col 26)
      new ColumnBase<PosMasterRow>({
        key: "balance",
        header: "Balance",
        widthPx: 75,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 20. Sold_Amt (Col 27)
      new ColumnBase<PosMasterRow>({
        key: "sold_amt",
        header: "Sold_Amt",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.yellow,
      }),

      // 21. Sold_Qty (Col 28)
      new ColumnBase<PosMasterRow>({
        key: "sold_qty",
        header: "Sold_Qty",
        widthPx: 70,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 22. Sold_Avg (Col 29)
      new ColumnBase<PosMasterRow>({
        key: "sold_avg",
        header: "Sold_Avg",
        widthPx: 70,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 23. Bought_Amt (Col 30)
      new ColumnBase<PosMasterRow>({
        key: "bought_amt",
        header: "Bought_Amt",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.yellow,
      }),

      // 24. Bought_Qty (Col 31)
      new ColumnBase<PosMasterRow>({
        key: "bought_qty",
        header: "Bought_Qty",
        widthPx: 70,
        align: "right",
        format: (v) => formatInt(v),
        color: colors.yellow,
      }),

      // 25. Bought_Avg (Col 32)
      new ColumnBase<PosMasterRow>({
        key: "bought_avg",
        header: "Bought_Avg",
        widthPx: 70,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 26. TheoPrc(T) (Col 33)
      new ColumnBase<PosMasterRow>({
        key: "theo_prc_t",
        header: "TheoPrc(T)",
        widthPx: 75,
        align: "right",
        format: (v) => formatNum(v, 4),
        color: (row: PosMasterRow) => {
          const prc   = row.last_prc_t  !== null && row.last_prc_t  !== undefined ? parseFloat(String(row.last_prc_t))  : 0;
          const ref   = row.last_prc_t_1 !== null && row.last_prc_t_1 !== undefined ? parseFloat(String(row.last_prc_t_1)) : 0;
          if (prc === 0) return colors.textSecondary;
          return getPriceColor(prc, ref, 0, 0);
        },
      }),

      // 27. TheoPrc(T-1) (Col 34)
      new ColumnBase<PosMasterRow>({
        key: "theo_prc_t_1",
        header: "TheoPrc(T-1)",
        widthPx: 75,
        align: "right",
        format: (v) => formatNum(v, 4),
        color: colors.increase,
      }),

      // 28. Delta(T) (Col 35) - strictly 3 decimal places
      new ColumnBase<PosMasterRow>({
        key: "delta_t",
        header: "Delta(T)",
        widthPx: 60,
        align: "right",
        format: (v) => formatDelta(v),
        color: colors.increase,
      }),

      // 29. DeltaLots(T) (Col 36) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "delta_lots_t",
        header: "DeltaLots(T)",
        widthPx: 70,
        align: "right",
        format: (v) => formatLots(v),
        color: colors.purple,
      }),

      // 30. DeltaCash(T) (Col 37) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "delta_cash_t",
        header: "DeltaCash(T)",
        widthPx: 90,
        align: "right",
        format: (v) => formatCash(v),
        color: colors.purple,
      }),

      // 31. DeltaCash(T-1) (Col 38)
      new ColumnBase<PosMasterRow>({
        key: "delta_cash_t_1",
        header: "DeltaCash(T-1)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v, 1),
        color: colors.purple,
      }),

      // 32. TrdDeltaLots(T) (Col 39) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "trd_delta_lots_t",
        header: "TrdDeltaLots(T)",
        widthPx: 70,
        align: "right",
        format: (v) => formatLots(v),
        color: colors.purple,
      }),

      // 33. TrdDeltaCash(T) (Col 40) - strictly 1 decimal place
      new ColumnBase<PosMasterRow>({
        key: "trd_delta_cash_t",
        header: "TrdDeltaCash(T)",
        widthPx: 90,
        align: "right",
        format: (v) => formatCash(v),
        color: colors.purple,
      }),

      // 34. %GammaAmt(T) (Col 41)
      new ColumnBase<PosMasterRow>({
        key: "gamma_amt_pct_t",
        header: "%GammaAmt(T)",
        widthPx: 75,
        align: "right",
        format: (v) => formatPct(v, 4),
        color: colors.increase,
      }),

      // 35. %Vega(T) (Col 42)
      new ColumnBase<PosMasterRow>({
        key: "vega_pct_t",
        header: "%Vega(T)",
        widthPx: 65,
        align: "right",
        format: (v) => formatPct(v, 4),
        color: colors.increase,
      }),

      // 36. CashVega(T) (Col 43)
      new ColumnBase<PosMasterRow>({
        key: "cash_vega_t",
        header: "CashVega(T)",
        widthPx: 80,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 37. Theta(T) (Col 44)
      new ColumnBase<PosMasterRow>({
        key: "theta_t",
        header: "Theta(T)",
        widthPx: 75,
        align: "right",
        format: (v) => formatNum(v, 6),
        color: colors.increase,
      }),

      // 38. CashTheta(T) (Col 45)
      new ColumnBase<PosMasterRow>({
        key: "cash_theta_t",
        header: "CashTheta(T)",
        widthPx: 80,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 39. TradingPnL(Theo) (Col 46)
      new ColumnBase<PosMasterRow>({
        key: "trading_pnl_theo",
        header: "TradingPnL(Theo)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 40. PositionPnL(Theo) (Col 47)
      new ColumnBase<PosMasterRow>({
        key: "position_pnl_theo",
        header: "PositionPnL(Theo)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 41. DeltaPnL (Col 48)
      new ColumnBase<PosMasterRow>({
        key: "delta_pnl",
        header: "DeltaPnL",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 42. GammaPnL (Col 49)
      new ColumnBase<PosMasterRow>({
        key: "gamma_pnl",
        header: "GammaPnL",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 43. ThetaPnL (Col 50)
      new ColumnBase<PosMasterRow>({
        key: "theta_pnl",
        header: "ThetaPnL",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 44. VegaPnL (Col 51)
      new ColumnBase<PosMasterRow>({
        key: "vega_pnl",
        header: "VegaPnL",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 45. UnexplainedPnL (Col 52)
      new ColumnBase<PosMasterRow>({
        key: "unexplained_pnl",
        header: "UnexplainedPnL",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 46. CapitalCost (Col 53)
      new ColumnBase<PosMasterRow>({
        key: "capital_cost",
        header: "CapitalCost",
        widthPx: 85,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.yellow,
      }),

      // 47. TotalPnL(Theo) - Daily (Col 54)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_theo",
        header: "TotalPnL(Theo)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 48. TotalPnL(MtM) - Daily (Col 55)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_mtm",
        header: "TotalPnL(MtM)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 49. PositionPnL(MtM) (Col 56)
      new ColumnBase<PosMasterRow>({
        key: "position_pnl_mtm",
        header: "PositionPnL(MtM)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 50. TradingPnL(MtM) (Col 57)
      new ColumnBase<PosMasterRow>({
        key: "trading_pnl_mtm",
        header: "TradingPnL(MtM)",
        widthPx: 90,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 51. TotalPnL(Theo) - Cumulative Annual (Col 58)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_theo_cum",
        header: "TotalPnL(Theo) Cum",
        widthPx: 95,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),

      // 52. TotalPnL(MtM) - Cumulative Annual (Col 59)
      new ColumnBase<PosMasterRow>({
        key: "total_pnl_mtm_cum",
        header: "TotalPnL(MtM) Cum",
        widthPx: 95,
        align: "right",
        format: (v) => formatNum(v),
        color: colors.purple,
      }),
    ];

    // Define the dynamic keys set (live calculated/Kb streaming in Overview & Summary tabs)
    const dynamicKeys = new Set(["ticker", "und_ticker", "last_prc_t", "last_prc_t_1", "net_chg_pct", "spot_prc_s", "theo_prc_t"]);

    // Override the getColor method on each column to enforce the tab-based coloring logic
    this.columns.forEach((col) => {
      const originalGetColor = col.getColor.bind(col);
      col.getColor = (row: PosMasterRow, getRow?: (symbol: string) => any): string => {
        // Ticker, Under_Ticker, Spot_Prc, and Theo_Prc always keep their color logics across all tabs
        if (col.key === "ticker" || col.key === "und_ticker" || col.key === "spot_prc_s" || col.key === "theo_prc_t") {
          return originalGetColor(row, getRow);
        }

        // If we are not on Overview or Summary tabs, use grey for everything else
        if (this.activeGroup !== "overview" && this.activeGroup !== "summary") {
          return colors.textMuted;
        }

        // If we are on Overview or Summary tabs, keep original colors for dynamic keys; everything else is grey
        if (dynamicKeys.has(col.key)) {
          return originalGetColor(row, getRow);
        }

        return colors.textMuted;
      };
    });
  }

  /** Keys that belong to each logical group. */
  private static readonly GROUP_KEYS: Record<Exclude<PosColumnGroup, "all">, string[]> = {
    // Overview = All 52 columns (handled dynamically in getColumnsByGroup())
    overview: [],
    // Summary = The old 13-column Overview sub-view (Market prices + Contract parameters)
    summary: [
      "ticker", "und_ticker",
      "last_prc_t", "last_prc_t_1", "net_chg_pct",
      "spot_prc_s", "theo_prc_t",
      "expiry", "dte", "strike_k",
      "cvr", "hedge_v_t", "rate",
    ],
    inventory: [
      "ticker", "und_ticker",
      "fund", "balance_t_1", "balance",
      "sold_amt", "sold_qty", "sold_avg",
      "bought_amt", "bought_qty", "bought_avg",
    ],
    greeks: [
      "ticker", "und_ticker", "last_prc_t", "spot_prc_s",
      "theo_prc_t", "theo_prc_t_1",
      "delta_t", "delta_lots_t", "delta_cash_t", "delta_cash_t_1",
      "trd_delta_lots_t", "trd_delta_cash_t",
      "gamma_amt_pct_t", "vega_pct_t", "cash_vega_t",
      "theta_t", "cash_theta_t",
    ],
    pnl: [
      "ticker", "und_ticker",
      "trading_pnl_theo", "position_pnl_theo",
      "delta_pnl", "gamma_pnl", "theta_pnl", "vega_pnl",
      "unexplained_pnl", "capital_cost",
      "total_pnl_theo", "total_pnl_mtm",
      "position_pnl_mtm", "trading_pnl_mtm",
      "total_pnl_theo_cum", "total_pnl_mtm_cum",
    ],
  };

  /**
   * Return columns filtered to the requested group.
   * - "all" returns every column (used for DisplayOption panel).
   * - Any named group returns only the columns defined for that group,
   *   preserving original column order from this.columns.
   */
  getColumnsByGroup(group: PosColumnGroup): ColumnBase<PosMasterRow>[] {
    if (group === "all" || group === "overview") return this.columns;
    const allowed = new Set(PosMasterTable.GROUP_KEYS[group]);
    return this.columns.filter((c) => allowed.has(c.key));
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
   * Flash color override for PosMaster — reuses and extends StockTable.getFlashColor logic.
   */
  getFlashColor(
    row: PosMasterRow,
    colKey: string,
    _direction: "up" | "down",
    getRow?: (symbol: string) => any
  ): string | undefined {
    const col = this.columns.find((c) => c.key === colKey);
    if (!col) return undefined;

    // 1. Live Data Input Columns: Ticker, LastPrice(T), Net_Chg(%)
    const cwLiveKeys = new Set(["ticker", "last_prc_t", "net_chg_pct"]);
    if (cwLiveKeys.has(colKey)) {
      const val = col.getValue(row);
      if (val === 0 || val === null || val === undefined) {
        return colors.textSecondary;
      }
      const color = col.getColor(row, getRow);
      if (color === colors.cyan) return colors.blue;
      return color;
    }

    // 1b. Und_Ticker + Spot_Prc(S): color based on the underlying's own live Ref/Ceil/Floor
    if (colKey === "und_ticker" || colKey === "spot_prc_s") {
      const undRow = getRow ? getRow(row.und_ticker) : null;
      const spot  = colKey === "und_ticker"
        ? (undRow?.Traded ?? 0)
        : (row.spot_prc_s !== null && row.spot_prc_s !== undefined ? parseFloat(String(row.spot_prc_s)) : 0);
      if (!spot) return colors.textSecondary;
      const ref   = undRow?.Ref   ?? 0;
      const ceil  = undRow?.Ceil  ?? 0;
      const floor = undRow?.Floor ?? 0;
      const c = getPriceColor(spot, ref, ceil, floor);
      return c === colors.cyan ? colors.blue : c;
    }

    // 2. Static / contract parameter columns do not flash or return default
    const staticKeys = new Set(["fund", "strike_k", "multiplier_m", "expiry", "rate", "cvr"]);
    if (staticKeys.has(colKey)) {
      return undefined;
    }

    // 3. For all other dynamic columns (theoreticals, Greeks, PnL, cash balance, quantity),
    // flash "Foreign's columns color" (colors.volData) when data changes.
    return colors.volData;
  }
}

export const posMasterTable = new PosMasterTable();
