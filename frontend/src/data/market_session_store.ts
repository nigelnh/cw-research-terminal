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
let timer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(fn => fn());
const elapsedNow = () => typeof performance === "undefined" ? Date.now() : performance.now();

export function marketNow(): number {
  return state.sessionContext
    ? clockBaseMs + elapsedNow() - receivedAt : Date.now();
}

export function acceptMarketContext(payload: { sessionContext?: SessionContext; feedStatus?: FeedStatus | null }): void {
  const next = payload.sessionContext;
  const previous = state.sessionContext;
  const nextServerMs = next ? Date.parse(next.serverTime) : Number.NaN;
  if (!next || !Number.isFinite(nextServerMs) ||
      (previous && (next.displaySessionDate < previous.displaySessionDate || nextServerMs < Date.parse(previous.serverTime)))) return;
  // A REST response or status frame can be newer than the previous payload while still
  // being older than the extrapolated clock at the instant it arrives. Resetting the
  // anchor to that payload made the header freeze or move backwards under load. Preserve
  // the authoritative context fields, but never move the running server clock backwards.
  const currentClock = previous ? marketNow() : nextServerMs;
  clockBaseMs = Math.max(nextServerMs, currentClock);
  receivedAt = elapsedNow();
  state = { sessionContext: next, feedStatus: payload.feedStatus ?? state.feedStatus };
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
}

export const marketSessionStore = {
  getSnapshot: () => state,
  subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; },
};
export function useMarketContext() {
  return useSyncExternalStore(marketSessionStore.subscribe, marketSessionStore.getSnapshot, marketSessionStore.getSnapshot);
}
