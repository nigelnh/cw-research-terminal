import { useSyncExternalStore } from "react";
import { appQueryClient } from "@/data/query/query_client";

export interface SessionContext {
  serverTime: string;
  displaySessionDate: string;
  latestCompletedSession: string;
  marketPhase: string;
  marketSessionActive: boolean;
  nextRolloverAt: string | null;
  calendarConfidence: string;
}
export interface FeedStatus {
  code: string;
  scope: string;
  message: string;
  checkedAt?: string;
  lastDataAt?: string | null;
  datasets?: FeedStatus[];
}
let state: { sessionContext: SessionContext | null; feedStatus: FeedStatus | null } = {
  sessionContext: null, feedStatus: null,
};
let receivedAt = 0;
let clockBaseMs = 0;
// The newest serverTime accepted, published or not: the guard against older payloads.
let latestServerMs = Number.NEGATIVE_INFINITY;
let timer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(fn => fn());
const elapsedNow = () => typeof performance === "undefined" ? Date.now() : performance.now();

export function marketNow(): number {
  return state.sessionContext
    ? clockBaseMs + elapsedNow() - receivedAt : Date.now();
}

// What a payload says once its clocks are set aside: serverTime, and the feed's check and
// last-data stamps, move on every frame, and marketNow() runs the clock between frames.
const contextKey = (ctx: SessionContext | null): string => {
  if (!ctx) return "";
  const { serverTime: _clock, ...rest } = ctx;
  return JSON.stringify(rest);
};
const feedKey = (feed: FeedStatus | null): string =>
  JSON.stringify(feed, (key, value) => (key === "checkedAt" || key === "lastDataAt" ? undefined : value));

/** Take a server payload's session context. Returns whether anything a consumer reads
 *  changed - only then does the store publish. Publishing every frame re-rendered every
 *  session consumer 40-70 times a second during a busy session (2026-10-12). */
export function acceptMarketContext(payload: { sessionContext?: SessionContext; feedStatus?: FeedStatus | null }): boolean {
  const next = payload.sessionContext;
  const previous = state.sessionContext;
  const nextServerMs = next ? Date.parse(next.serverTime) : Number.NaN;
  if (!next || !Number.isFinite(nextServerMs) ||
      (previous && (next.displaySessionDate < previous.displaySessionDate || nextServerMs < latestServerMs))) return false;
  // A REST response or status frame can be newer than the previous payload while still
  // being older than the extrapolated clock at the instant it arrives. Resetting the
  // anchor to that payload made the header freeze or move backwards under load. Preserve
  // the authoritative context fields, but never move the running server clock backwards.
  const currentClock = previous ? marketNow() : nextServerMs;
  clockBaseMs = Math.max(nextServerMs, currentClock);
  receivedAt = elapsedNow();
  latestServerMs = nextServerMs;
  const feedStatus = payload.feedStatus ?? state.feedStatus;
  if (previous && contextKey(previous) === contextKey(next) && feedKey(state.feedStatus) === feedKey(feedStatus)) return false;
  state = { sessionContext: next, feedStatus };
  if (timer) clearTimeout(timer);
  if (previous && previous.displaySessionDate !== next.displaySessionDate) void appQueryClient.invalidateQueries();
  const delay = next.nextRolloverAt ? Date.parse(next.nextRolloverAt) - clockBaseMs : 0;
  if (delay > 0) timer = setTimeout(() => {
    // The server already supplied this trading-day boundary. No browser holiday logic.
    const boundary = next.nextRolloverAt!;
    acceptMarketContext({ sessionContext: { ...next, serverTime: boundary,
      displaySessionDate: new Date(Date.parse(boundary) + 7 * 3600000).toISOString().slice(0, 10),
      latestCompletedSession: next.displaySessionDate,
      nextRolloverAt: null, marketPhase: "PRE_OPEN", marketSessionActive: false } });
  }, Math.min(delay, 2147483647));
  notify();
  return true;
}

export const marketSessionStore = {
  getSnapshot: () => state,
  subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
};
export function useMarketContext() {
  return useSyncExternalStore(marketSessionStore.subscribe, marketSessionStore.getSnapshot, marketSessionStore.getSnapshot);
}
