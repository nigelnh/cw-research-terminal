import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { backendClient, type AiQuota } from "@/data/backend/backend_client";
import { queryKeys } from "@/data/query/query_keys";
import { useAuth } from "@/data/auth";

/**
 * Today's AI-chat usage for the current caller, from `/api/ai/quota` - so the panel can
 * show the allowance BEFORE a 429, not after. Keyed by identity so it resets cleanly on
 * sign-in / sign-out. Call `refresh()` right after a chat send to reflect the consumed
 * request.
 */
export function useAiQuota() {
  const { user, status } = useAuth();
  const subject = user?.id ?? "anon";
  const queryClient = useQueryClient();

  const query = useQuery<AiQuota>({
    queryKey: queryKeys.aiQuota(subject),
    queryFn: ({ signal }) => backendClient.getAiQuota(signal),
    // Don't fetch until the auth boundary has settled, so the first read is on the right
    // identity (a guest read then an immediate signed-in read otherwise).
    enabled: status !== "loading",
    staleTime: 15_000,
    retry: 1,
    refetchOnWindowFocus: true,
  });

  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.aiQuota(subject) });
  }, [queryClient, subject]);

  return { quota: query.data, isLoading: query.isLoading, refresh };
}
