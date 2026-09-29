/**
 * Today's daily candle, kept current from the live quote.
 *
 * The history endpoint serves today's bar as a REALTIME_SESSION snapshot taken when the
 * query ran, and the query refetches once a minute - so between refetches the candle
 * trails the tape. The time & sales panel beside the chart printed 20,200 while the
 * candle and its OHLC readout still closed at 20,250.
 *
 * For the DAILY interval the live quote's session open / high / low / last / total volume
 * are today's bar, not an approximation of it, so the last candle is patched from the
 * quote instead of waiting for the next refetch.
 *
 * Deliberately 1D only. An intraday candle is a slice of the session; copying session
 * high/low/volume into it is the fabrication the old CurrentBarBuilder was removed for.
 * That builder also bucketed days in UTC; this keys everything on the ICT session date.
 *
 * Nothing is invented: without a matched trade (lastPrice > 0) nothing changes, a quote is
 * only ever applied to the bar for its own session, and a new bar is opened only from
 * real session aggregates.
 */

import type { HistoricalBar, MarketQuote } from "@/domain/models";

const ICT_OFFSET_MS = 7 * 60 * 60 * 1000;
const SESSION_DATE = /^\d{4}-\d{2}-\d{2}/;

/** A usable price or volume: finite and strictly positive. Pre-open resets arrive as 0. */
function positive(value: number | null | undefined): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function barSessionDate(bar: HistoricalBar): string | null {
  const raw = bar.sessionDate ?? bar.date;
  return typeof raw === "string" && SESSION_DATE.test(raw) ? raw.slice(0, 10) : null;
}

/**
 * The ICT session a quote belongs to: its own stamp when it carries one, otherwise the
 * ICT calendar date of its trade. Never the browser's clock - a cached quote belongs to
 * when it was observed.
 */
export function quoteSessionDate(quote: MarketQuote): string | null {
  const stamped = quote.marketSessionDate;
  if (typeof stamped === "string" && SESSION_DATE.test(stamped)) return stamped.slice(0, 10);
  return ictDate(quote.tradeTimestamp ?? quote.exchangeTimestamp ?? quote.sourceTimestamp);
}

/** The ICT calendar date of an epoch stamp (seconds or milliseconds). */
function ictDate(ts: number | null | undefined): string | null {
  if (typeof ts !== "number" || !Number.isFinite(ts) || ts <= 0) return null;
  const ms = ts > 1e11 ? ts : ts * 1000;
  return new Date(ms + ICT_OFFSET_MS).toISOString().slice(0, 10);
}

function sameBar(a: HistoricalBar, b: HistoricalBar): boolean {
  return (
    a.open === b.open &&
    a.high === b.high &&
    a.low === b.low &&
    a.close === b.close &&
    a.volume === b.volume
  );
}

/**
 * Returns `bars` with the session's candle brought up to the live quote.
 *
 * Returns the SAME array when there is nothing to apply, so a quote that does not move the
 * candle does not hand the chart a new array to redraw.
 */
export function withLiveSessionBar(
  bars: HistoricalBar[],
  quote: MarketQuote | null | undefined,
): HistoricalBar[] {
  if (!quote || bars.length === 0) return bars;
  const last = positive(quote.lastPrice);
  if (last === null) return bars;
  const session = quoteSessionDate(quote);
  if (session === null) return bars;

  const tail = bars[bars.length - 1];
  const tailSession = barSessionDate(tail);
  if (tailSession === null) return bars;

  const sessionHigh = positive(quote.highPrice);
  const sessionLow = positive(quote.lowPrice);
  const sessionVolume = positive(quote.totalVolume);

  if (tailSession === session) {
    // Both are real observations of the same session, so the envelope is the union of the
    // two and the latest print closes it. Volume is the session total either way; the
    // larger one wins so a lagging source can never roll the bar back.
    const highs = [tail.high, sessionHigh, last].filter((v): v is number => positive(v) !== null);
    const lows = [tail.low, sessionLow, last].filter((v): v is number => positive(v) !== null);
    const patched: HistoricalBar = {
      ...tail,
      open: tail.open ?? positive(quote.openPrice),
      high: Math.max(...highs),
      low: Math.min(...lows),
      close: last,
      volume:
        sessionVolume !== null && sessionVolume > (tail.volume ?? 0) ? sessionVolume : tail.volume,
    };
    return sameBar(patched, tail) ? bars : [...bars.slice(0, -1), patched];
  }

  if (tailSession < session) {
    // The session has traded but history has not caught up yet. Opening a bar the backend
    // has not confirmed is the riskiest thing here, so it needs the exchange's own session
    // aggregates AND a trade timestamped inside this session - a pre-open quote stamped
    // with the new date but still carrying yesterday's figures must not become a candle.
    const open = positive(quote.openPrice);
    if (open === null || sessionHigh === null || sessionLow === null || sessionVolume === null) {
      return bars;
    }
    if (ictDate(quote.tradeTimestamp) !== session) return bars;
    return [
      ...bars,
      {
        symbol: tail.symbol,
        date: session,
        sessionDate: session,
        open,
        high: Math.max(sessionHigh, last),
        low: Math.min(sessionLow, last),
        close: last,
        volume: sessionVolume,
        complete: false,
      },
    ];
  }

  // A quote from an earlier session than the newest bar never touches it.
  return bars;
}
