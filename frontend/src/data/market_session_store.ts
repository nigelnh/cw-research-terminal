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
let timer: ReturnType<typeof setTimeout> | undefined;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach(fn => fn());
const elapsedNow = () => typeof performance === "undefined" ? Date.now() : performance.now();

export function marketNow(): number {
  return state.sessionContext
    ? Date.parse(state.sessionContext.serverTime) + elapsedNow() - receivedAt : Date.now();
}

export function acceptMarketContext(payload: { sessionContext?: SessionContext; feedStatus?: FeedStatus | null }): void {
  const next = payload.sessionContext;
  const previous = state.sessionContext;
  if (!next || !Number.isFinite(Date.parse(next.serverTime)) ||
      (previous && (next.displaySessionDate < previous.displaySessionDate || Date.parse(next.serverTime) < Date.parse(previous.serverTime)))) return;
  receivedAt = elapsedNow();
  state = { sessionContext: next, feedStatus: payload.feedStatus ?? state.feedStatus };
  if (timer) clearTimeout(timer);
  if (previous && previous.displaySessionDate !== next.displaySessionDate) void appQueryClient.invalidateQueries();
  const delay = next.nextRolloverAt ? Date.parse(next.nextRolloverAt) - Date.parse(next.serverTime) : 0;
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
