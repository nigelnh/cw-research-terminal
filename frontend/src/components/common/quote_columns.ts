import {
  DASH,
  fmtChg,
  fmtIV,
  fmtPrice,
  fmtRatio,
  fmtVol,
  priceBandColor,
  priceColor,
} from "./grid_table";

/** Shared by the watchlist and the instrument's STATS readout. */
export const QUOTE_COLUMNS = [
  { key: "symbol", label: "SYMBOL" },
  { key: "ceiling", label: "CEIL" },
  { key: "floor", label: "FLOOR" },
  { key: "ref", label: "REF" },
  { key: "ivBid", label: "IV_BID" },
  { key: "bid", label: "BID_PRC" },
  { key: "ivTrade", label: "IV_TRD" },
  { key: "last", label: "TRD_PRC" },
  { key: "tradingValue", label: "TRD_AMT" },
  { key: "change", label: "+/-" },
  { key: "chgPct", label: "%CHG" },
  { key: "ivAsk", label: "IV_ASK" },
  { key: "ask", label: "ASK_PRC" },
  { key: "vol", label: "VOLUME" },
  { key: "strike", label: "STRIKE" },
  { key: "ratio", label: "RATIO" },
  { key: "lastTradingDate", label: "LAST_TRD_DATE" },
  { key: "dte", label: "DTE" },
  { key: "issuer", label: "ISSUER" },
] as const;
export type QuoteColumnKey = (typeof QUOTE_COLUMNS)[number]["key"];
export const QUOTE_COLUMN_PULSE_FIELD: Partial<Record<QuoteColumnKey, string>> = {
  bid: "bidPrice",
  ask: "askPrice",
  last: "lastPrice",
  tradingValue: "tradingValue",
  change: "priceChange",
  chgPct: "priceChangePercent",
  vol: "totalVolume",
  ivBid: "ivBid",
  ivTrade: "ivTrade",
  ivAsk: "ivAsk",
};
export const QUOTE_COLUMN_HINTS: Partial<Record<QuoteColumnKey, string>> = {
  tradingValue: "Session traded value (VND)",
  lastTradingDate: "Last trading date (YYYY-MM-DD)",
};
export interface QuoteTableValues {
  symbol: string;
  issuer?: string | null;
  ref: number | null;
  ceiling: number | null;
  floor: number | null;
  bid: number | null;
  ask: number | null;
  last: number | null;
  tradingValue: number | null;
  change?: number | null;
  chgPct: number | null;
  vol: number | null;
  strike: number | null;
  ratio: number | null;
  ivBid: number | null;
  ivTrade: number | null;
  ivAsk: number | null;
  lastTradingDate: string | null;
  dteText: string;
}

export function quoteCell(
  row: QuoteTableValues,
  key: QuoteColumnKey,
): { text: string; color: string } {
  const muted = "var(--t-50)";
  switch (key) {
    case "symbol":
      return { text: row.symbol, color: "var(--accent)" };
    case "ceiling":
    case "floor":
    case "ref":
      return {
        text: fmtPrice(row[key]),
        color: priceBandColor(row[key], key === "ref" ? "reference" : key),
      };
    case "bid":
    case "ask":
    case "last":
      return { text: fmtPrice(row[key]), color: priceColor(row[key], row) };
    case "ivBid":
    case "ivTrade":
    case "ivAsk":
      return {
        text: fmtIV(row[key]),
        color: key === "ivTrade" ? "var(--t-85)" : muted,
      };
    case "change": {
      const amount = typeof row.change === "number"
        ? row.change
        : row.last !== null && row.ref !== null
          ? row.last - row.ref
          : null;
      return {
        text:
          amount === null
            ? DASH
            : `${amount > 0 ? "+" : amount < 0 ? "−" : ""}${fmtPrice(Math.abs(amount))}`,
        color:
          amount === null
            ? muted
            : amount > 0
              ? "var(--up)"
              : amount < 0
                ? "var(--down)"
                : "var(--flat)",
      };
    }
    case "chgPct":
      return fmtChg(row.chgPct);
    case "vol":
      return { text: fmtVol(row.vol), color: muted };
    case "tradingValue":
      return { text: fmtPrice(row.tradingValue), color: muted };
    case "strike":
      return { text: fmtPrice(row.strike), color: "var(--t-60)" };
    case "ratio":
      return { text: fmtRatio(row.ratio), color: muted };
    case "lastTradingDate":
      return { text: row.lastTradingDate?.slice(0, 10) || DASH, color: muted };
    case "issuer":
      return { text: row.issuer || DASH, color: muted };
    case "dte":
      return { text: row.dteText, color: "var(--t-46)" };
  }
}
