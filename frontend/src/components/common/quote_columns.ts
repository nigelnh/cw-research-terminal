import {
  DASH,
  fmtChg,
  fmtIV,
  fmtPrice,
  fmtRatio,
  fmtVol,
  priceBandColor,
  priceColor,
  priceTone,
} from "./grid_table";
import type { FlashTone } from "./realtime_value";

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
  { key: "tradedQuantity", label: "TRD_AMT" },
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
  tradedQuantity: "tradedQuantity",
  change: "priceChange",
  chgPct: "priceChangePercent",
  vol: "totalVolume",
  ivBid: "ivBid",
  ivTrade: "ivTrade",
  ivAsk: "ivAsk",
};
export const QUOTE_COLUMN_HINTS: Partial<Record<QuoteColumnKey, string>> = {
  tradedQuantity: "Quantity of the most recent match",
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
  tradedQuantity?: number | null;
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

/**
 * One cell's text, colour, and realtime-flash tone.
 *
 * `tone` is the price band this cell belongs to; the flash reads it so the wash and the
 * digits always agree (ceiling magenta, floor blue, reference flat-yellow). Cells that are
 * not price-derived leave it undefined and keep the plain direction flash.
 */
export function quoteCell(
  row: QuoteTableValues,
  key: QuoteColumnKey,
): { text: string; color: string; tone?: FlashTone } {
  const muted = "var(--t-50)";
  switch (key) {
    case "symbol":
      return { text: row.symbol, color: priceColor(row.last, row), tone: priceTone(row.last, row) };
    case "ceiling":
    case "floor":
    case "ref":
      return {
        text: fmtPrice(row[key]),
        color: priceBandColor(row[key], key === "ref" ? "reference" : key),
        tone: key === "ref" ? "flat" : key,
      };
    case "bid":
    case "ask":
    case "last":
      return {
        text: fmtPrice(row[key]),
        color: priceColor(row[key], row),
        tone: priceTone(row[key], row),
      };
    case "ivBid":
    case "ivTrade":
    case "ivAsk":
      return { text: fmtIV(row[key]), color: "var(--t-92)" };
    case "change": {
      const amount = typeof row.change === "number"
        ? row.change
        : row.change === undefined && row.last !== null && row.ref !== null
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
        tone: amount === null ? undefined : amount > 0 ? "up" : amount < 0 ? "down" : "flat",
      };
    }
    case "chgPct": {
      const c = fmtChg(row.chgPct);
      const p = row.chgPct;
      return {
        ...c,
        tone: typeof p !== "number" || Number.isNaN(p) ? undefined : p > 0 ? "up" : p < 0 ? "down" : "flat",
      };
    }
    case "vol":
      return { text: fmtVol(row.vol), color: "var(--t-92)" };
    case "tradedQuantity": {
      // Size of the most recent match, so it belongs to the same band as the price that
      // matched. A non-positive size is "no match observed" - never a literal 0 (a
      // MatchVolume-0 frame used to write one straight into the column).
      const qty =
        typeof row.tradedQuantity === "number" && row.tradedQuantity > 0
          ? row.tradedQuantity
          : null;
      return {
        text: qty === null ? DASH : fmtVol(qty),
        color: qty === null ? muted : priceColor(row.last, row),
        tone: qty === null ? undefined : priceTone(row.last, row),
      };
    }
    case "strike":
      return { text: fmtPrice(row.strike), color: "var(--t-92)" };
    case "ratio":
      return { text: fmtRatio(row.ratio), color: "var(--t-92)" };
    case "lastTradingDate":
      return { text: row.lastTradingDate?.slice(0, 10) || DASH, color: "var(--t-92)" };
    case "issuer":
      return { text: row.issuer || DASH, color: "var(--t-92)" };
    case "dte":
      return { text: row.dteText, color: "var(--t-92)" };
  }
}
