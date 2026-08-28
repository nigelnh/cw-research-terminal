import { QueryClient } from "@tanstack/react-query";

/**
 * Shared QueryClient for all request/response server state.
 *
 * Defaults are tuned for a research terminal where:
 *  - historical bars are persisted server-side and effectively immutable once a session
 *    is complete, so long staleTime + no window-focus refetch avoids needless traffic;
 *  - the backend is PostgreSQL-first, so there is no rate-limit reason to poll.
 * Realtime ticks/analytics NEVER go through this - they stay in the WebSocket external store.
 */
export function createAppQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Historical data does not change within a viewing session -> treat as fresh
        // for 5 minutes, keep in memory 30 minutes after last use.
        staleTime: 5 * 60_000,
        gcTime: 30 * 60_000,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        refetchOnMount: false,
        retry: (failureCount, error) => {
          // Do not retry deterministic client errors (bad range / symbol -> HTTP 4xx).
          const msg = error instanceof Error ? error.message : String(error);
          if (/HTTP 4\d\d/.test(msg)) return false;
          return failureCount < 2;
        },
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
      },
      mutations: { retry: false },
    },
  });
}

export const appQueryClient = createAppQueryClient();
