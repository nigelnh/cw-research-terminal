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

/**
 * The watchlist's STOCK view: a price board. The warrant-only columns (IVs, strike,
 * ratio, dates, issuer) are dropped for three levels of depth either side of the last
 * match, the session's high and low, and foreign buy / sell / remaining room.
 */
export const STOCK_BOARD_COLUMNS = [
  { key: "symbol", label: "SYMBOL" },
  { key: "ceiling", label: "CEIL" },
  { key: "floor", label: "FLOOR" },
  { key: "ref", label: "REF" },
  { key: "bid3", label: "BID_PRC_3" },
  { key: "bid3Qty", label: "BID_AMT_3" },
  { key: "bid2", label: "BID_PRC_2" },
  { key: "bid2Qty", label: "BID_AMT_2" },
  { key: "bid", label: "BID_PRC_1" },
  { key: "bidQty", label: "BID_AMT_1" },
  { key: "last", label: "TRD_PRC" },
  { key: "tradedQuantity", label: "TRD_AMT" },
  { key: "change", label: "+/-" },
  { key: "chgPct", label: "%CHG" },
  { key: "ask", label: "ASK_PRC_1" },
  { key: "askQty", label: "ASK_AMT_1" },
  { key: "ask2", label: "ASK_PRC_2" },
  { key: "ask2Qty", label: "ASK_AMT_2" },
  { key: "ask3", label: "ASK_PRC_3" },
  { key: "ask3Qty", label: "ASK_AMT_3" },
  { key: "vol", label: "VOLUME" },
  { key: "high", label: "HIGH" },
  { key: "low", label: "LOW" },
  { key: "foreignBuy", label: "F_BUY" },
  { key: "foreignSell", label: "F_SELL" },
  { key: "foreignRoom", label: "F_ROOM" },
] as const;
export type StockBoardColumnKey = (typeof STOCK_BOARD_COLUMNS)[number]["key"];
/** Every column the watchlist can show, in either column set. */
export type WatchlistColumnKey = QuoteColumnKey | StockBoardColumnKey;
type BoardOnlyKey = Exclude<StockBoardColumnKey, QuoteColumnKey>;

export const QUOTE_COLUMN_PULSE_FIELD: Partial<Record<WatchlistColumnKey, string>> = {
  bid2: "bid2Price",
  bid3: "bid3Price",
  ask2: "ask2Price",
  ask3: "ask3Price",
  bidQty: "bidQuantity",
  bid2Qty: "bid2Quantity",
  bid3Qty: "bid3Quantity",
  askQty: "askQuantity",
  ask2Qty: "ask2Quantity",
  ask3Qty: "ask3Quantity",
  high: "highPrice",
  low: "lowPrice",
  foreignBuy: "foreignBuy",
  foreignSell: "foreignSell",
  foreignRoom: "foreignRoom",
  bid: "bidPrice",
  ask: "askPrice",
  // A matched order is one visual event. Use its shared pulse so all four trade fields
  // flash together even when the latest price, size, or change repeats the prior print.
  last: "trade",
  tradedQuantity: "trade",
  change: "trade",
  chgPct: "trade",
  vol: "totalVolume",
  ivBid: "ivBid",
  ivTrade: "ivTrade",
  ivAsk: "ivAsk",
};
export const QUOTE_COLUMN_HINTS: Partial<Record<WatchlistColumnKey, string>> = {
  tradedQuantity: "Quantity of the most recent match",
  lastTradingDate: "Last trading date (YYYY-MM-DD)",
  bid3: "Third-best bid price",
  bid3Qty: "Quantity bid at the third-best price",
  bid2: "Second-best bid price",
  bid2Qty: "Quantity bid at the second-best price",
  bidQty: "Quantity bid at the best price",
  askQty: "Quantity offered at the best price",
  ask2: "Second-best ask price",
  ask2Qty: "Quantity offered at the second-best price",
  ask3: "Third-best ask price",
  ask3Qty: "Quantity offered at the third-best price",
  high: "Highest match this session",
  low: "Lowest match this session",
  foreignBuy: "Shares foreign investors bought this session",
  foreignSell: "Shares foreign investors sold this session",
  foreignRoom: "Shares foreign investors may still buy (remaining room)",
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

/** The stock board's extra values, on top of the shared quote columns. */
export interface StockBoardValues extends QuoteTableValues {
  bid2: number | null;
  bid3: number | null;
  ask2: number | null;
  ask3: number | null;
  bidQty: number | null;
  bid2Qty: number | null;
  bid3Qty: number | null;
  askQty: number | null;
  ask2Qty: number | null;
  ask3Qty: number | null;
  high: number | null;
  low: number | null;
  foreignBuy: number | null;
  foreignSell: number | null;
  foreignRoom: number | null;
}

/** Each depth quantity takes the colour band of the price it sits at, as TRD_AMT does. */
const QUANTITY_PRICE: Record<
  "bidQty" | "bid2Qty" | "bid3Qty" | "askQty" | "ask2Qty" | "ask3Qty",
  "bid" | "bid2" | "bid3" | "ask" | "ask2" | "ask3"
> = {
  bidQty: "bid", bid2Qty: "bid2", bid3Qty: "bid3",
  askQty: "ask", ask2Qty: "ask2", ask3Qty: "ask3",
};

/** One watchlist cell, for either column set. */
export function watchlistCell(
  row: StockBoardValues,
  key: WatchlistColumnKey,
): { text: string; color: string; tone?: FlashTone } {
  if (!isBoardOnlyKey(key)) return quoteCell(row, key);
  switch (key) {
    case "bid2":
    case "bid3":
    case "ask2":
    case "ask3":
    case "high":
    case "low":
      return { text: fmtPrice(row[key]), color: priceColor(row[key], row), tone: priceTone(row[key], row) };
    case "bidQty":
    case "bid2Qty":
    case "bid3Qty":
    case "askQty":
    case "ask2Qty":
    case "ask3Qty": {
      const price = row[QUANTITY_PRICE[key]];
      return { text: fmtVol(row[key]), color: priceColor(price, row), tone: priceTone(price, row) };
    }
    case "foreignBuy":
    case "foreignSell":
    case "foreignRoom":
      return { text: fmtVol(row[key]), color: "var(--t-92)", tone: "neutral" };
  }
}

const BOARD_ONLY = new Set<string>(
  STOCK_BOARD_COLUMNS.map((c) => c.key).filter((key) => !QUOTE_COLUMNS.some((c) => c.key === key)),
);
function isBoardOnlyKey(key: WatchlistColumnKey): key is BoardOnlyKey {
  return BOARD_ONLY.has(key);
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
      return { text: fmtIV(row[key]), color: "var(--t-92)", tone: "neutral" };
    case "change": {
      const amount = typeof row.change === "number"
        ? row.change
        : row.change === undefined && row.last !== null && row.ref !== null
          ? row.last - row.ref
          : null;
      return {
        text: amount === null ? DASH : fmtPrice(Math.abs(amount)),
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
      return { text: fmtVol(row.vol), color: "var(--t-92)", tone: "neutral" };
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
