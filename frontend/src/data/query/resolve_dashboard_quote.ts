import type { MarketQuote } from "@/domain/models";
import { quoteTimestamp, type DisplayState, type RowProvenance } from "@/domain/temporal";

const TRADE = ["lastPrice", "openPrice", "highPrice", "lowPrice", "averagePrice",
  "tradedQuantity", "totalVolume", "tradingValue", "priceChange", "priceChangePercent",
  "tradeTimestamp", "sourceTimestamp", "exchangeTimestamp", "tradeReceivedTimestamp"] as const;
const BOOK = ["bidPrice", "bidQuantity", "askPrice", "askQuantity", "bid2Price", "bid2Quantity",
  "ask2Price", "ask2Quantity", "bid3Price", "bid3Quantity", "ask3Price", "ask3Quantity",
  "bookTimestamp", "bookReceivedTimestamp"] as const;
const REFERENCE = ["referencePrice", "ceilingPrice", "floorPrice", "referenceTimestamp", "referenceSessionDate"] as const;

export function isQuoteTimestampEligible(stamp: string | null, now = Date.now()): boolean {
  if (!stamp) return false;
  const age = now - new Date(stamp).getTime();
  return Number.isFinite(age) && age >= 0 && age <= 180_000;
}

/** Merge independently dated observations, not whole quote objects or receipt clocks. */
export function resolveDashboardQuote(
  fallback: MarketQuote, live: MarketQuote | undefined, source: RowProvenance,
  active: boolean, now = Date.now(),
): { quote: MarketQuote; provenance: RowProvenance; displayState: DisplayState } {
  const quote = { ...fallback };
  const provenance = { ...source, quote: { ...source.quote }, book: { ...source.book } };
  const vnNow = new Date(now + 7 * 3600_000).toISOString();
  const today = vnNow.slice(0, 10);
  const session = live?.marketSessionDate;
  const copy = (keys: readonly (keyof MarketQuote)[], from?: MarketQuote) => {
    Object.assign(quote, Object.fromEntries(keys.map(key => [key, from?.[key] ?? null])));
  };
  // Like `copy`, but only for fields `from` actually has - never blanks a field `from`
  // is simply silent on. Bands the live snapshot resolver derives for a CW (ceilingPrice /
  // floorPrice from the underlying's limit, since the provider has no CW band endpoint)
  // only ever live on `fallback`; `live` (the realtime quote) never carries them, so a
  // blind `copy(REFERENCE, live)` would null them out the moment any live reference field
  // (e.g. referencePrice) updates.
  const copyDefined = (keys: readonly (keyof MarketQuote)[], from?: MarketQuote) => {
    Object.assign(
      quote,
      Object.fromEntries(keys.filter(key => from?.[key] != null).map(key => [key, from![key]])),
    );
  };
  if (live && session && session <= today) {
    for (const [group, fields, stamp, hasObservation] of [
      ["quote", TRADE, quoteTimestamp(live), live.lastPrice !== null],
      ["book", BOOK, live.bookTimestamp ? new Date(live.bookTimestamp).toISOString() : null,
        live.bidPrice !== null || live.askPrice !== null],
    ] as const) {
      const previous = provenance[group];
      const previousSession = previous.sessionDate;
      if (previousSession && session < previousSession) continue;
      if (previousSession && session > previousSession) {
        copy(fields);
        provenance[group] = { state: "UNAVAILABLE", source: "NONE", sessionDate: session,
          note: "Awaiting a new-session observation" };
      }
      if (!hasObservation || !stamp || new Date(stamp).getTime() > now) continue;
      // Compare instants, not strings with different UTC offsets.
      if (session === previousSession && previous.asOf && Date.parse(stamp) < Date.parse(previous.asOf)) continue;
      copy(fields, live);
      const fresh = active && session === today && isQuoteTimestampEligible(stamp, now);
      provenance[group] = {
        state: fresh ? "LIVE" : session === today && vnNow.slice(11, 16) < "15:00" ? "SESSION_SNAPSHOT" : "LAST_SESSION",
        source: "LIVE_FEED", asOf: stamp, sessionDate: session, stale: active && !fresh,
      };
      quote.marketSessionDate = session;
      quote.realtimePulses = live.realtimePulses;
    }
    if (provenance.reference?.sessionDate && session > provenance.reference.sessionDate) {
      copy(REFERENCE);
      provenance.reference = { state: "UNAVAILABLE", source: "NONE", sessionDate: session };
    }
  }
  if (live?.referenceSessionDate && live.referenceSessionDate <= today &&
      (!provenance.reference?.sessionDate || live.referenceSessionDate >= provenance.reference.sessionDate) &&
      (!provenance.reference?.asOf || !live.referenceTimestamp || live.referenceTimestamp >= Date.parse(provenance.reference.asOf))) {
    copyDefined(REFERENCE, live);
    provenance.reference = { state: "DERIVED", source: "SESSION_REFERENCE",
      sessionDate: live.referenceSessionDate,
      asOf: live.referenceTimestamp ? new Date(live.referenceTimestamp).toISOString() : null };
  }
  const states = [provenance.quote.state, provenance.book.state].filter(state => state !== "UNAVAILABLE");
  const displayState: DisplayState = !states.length ? "UNAVAILABLE"
    : states.every(state => state === "LIVE") ? "LIVE"
    : states.includes("LIVE") ? "MIXED"
    : states.every(state => state === "SESSION_SNAPSHOT") ? "SESSION_SNAPSHOT" : "LAST_SESSION";
  return { quote, provenance, displayState };
}
