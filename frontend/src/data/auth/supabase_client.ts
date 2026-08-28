/**
 * The ONLY module in the app that imports `@supabase/supabase-js`.
 *
 * Everything else talks to `useAuth()` / the small `AuthSession` shape. If we ever swap
 * providers, this file and `auth_provider.tsx` are the whole blast radius.
 *
 * Config comes from two client-safe env vars (publishable values only - never a
 * service-role key). When either is missing the app runs fully anonymous: `getSupabase()`
 * returns `null` and the "Sign in" control is hidden.
 */
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

let cached: SupabaseClient | null | undefined;

function readConfig(): { url: string; anonKey: string } | null {
  const env = import.meta.env as Record<string, string | undefined>;
  const url = (env.VITE_SUPABASE_URL ?? "").trim();
  const anonKey = (env.VITE_SUPABASE_ANON_KEY ?? "").trim();
  if (!url || !anonKey) return null;
  return { url, anonKey };
}

export function isAuthConfigured(): boolean {
  return readConfig() !== null;
}

/** The shared Supabase client, or `null` when auth is not configured on this build. */
export function getSupabase(): SupabaseClient | null {
  if (cached !== undefined) return cached;
  const cfg = readConfig();
  if (!cfg) {
    cached = null;
    return null;
  }
  cached = createClient(cfg.url, cfg.anonKey, {
    auth: {
      // Default PKCE flow. supabase-js parses the `?code=` callback on load and then we
      // scrub the auth params from the URL (see auth_provider) so research state (?tab,
      // ?symbol, ?range, ?interval) is preserved.
      detectSessionInUrl: true,
      persistSession: true,
      autoRefreshToken: true,
      flowType: "pkce",
    },
  });
  return cached;
}

/** Test seam: drop the memoized client so a test can re-read env. */
export function __resetSupabaseForTests(): void {
  cached = undefined;
}
