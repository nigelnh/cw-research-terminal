import { useQuery } from "@tanstack/react-query";
import type { CoveredWarrant } from "@/domain/models";
import { providers } from "@/data/providers";
import { queryKeys } from "./query_keys";

/**
 * Static covered-warrant universe metadata (no realtime ticks). Server state -> cached.
 * The research table filters/sorts this list client-side; those filters stay local UI state.
 */
export function useActiveWarrants(filter?: {
  issuer?: string | null;
  underlying?: string | null;
  /** When "ALL", browse the whole discovered registry (research tab). */
  status?: "ACTIVE" | "ALL";
}) {
  const query = useQuery({
    queryKey: queryKeys.instruments.activeWarrants(filter),
    queryFn: () =>
      providers.instruments.getActiveCoveredWarrants({
        issuer: filter?.issuer ?? undefined,
        underlyingSymbol: filter?.underlying ?? undefined,
        status: filter?.status ?? "ACTIVE",
      }),
    staleTime: 10 * 60_000, // universe metadata changes rarely
  });

  return {
    instruments: (query.data ?? []) as CoveredWarrant[],
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error,
  };
}
