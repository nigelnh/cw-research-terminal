/**
 * Frontend auth/session boundary.
 *
 * Exposes ONLY what the app needs - `{ user, status, isConfigured, signIn*, signOut }`.
 * The raw Supabase `Session`/`SupabaseClient` never leave this file.
 *
 * Responsibilities:
 *  - restore an existing session on load, follow token refreshes, sign in / out;
 *  - keep the backend API client's bearer token current (module-level, synchronous read);
 *  - on ANY identity boundary (anon->user, user A->user B, user->anon) call
 *    `queryClient.clear()` so no user-scoped server cache can bleed across accounts;
 *  - after an OAuth / magic-link callback, strip the auth params from the URL while
 *    preserving research state (`?tab`, `?symbol`, `?range`, `?interval`).
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { setAccessTokenProvider } from "@/data/backend/backend_client";
import { getSupabase, isAuthConfigured } from "./supabase_client";

export interface AuthUser {
  /** Verified Supabase subject (JWT `sub`). The ownership key everywhere. */
  id: string;
  email: string | null;
}

export type AuthStatus = "loading" | "anonymous" | "authenticated";

export interface AuthContextValue {
  user: AuthUser | null;
  status: AuthStatus;
  /** false when this build has no Supabase config - the whole UI stays anonymous-only. */
  isConfigured: boolean;
  signInWithGoogle: () => Promise<void>;
  signInWithEmail: (email: string) => Promise<{ ok: boolean; message: string }>;
  signOut: () => Promise<void>;
}

const noopAsync = async () => {};

const DEFAULT_VALUE: AuthContextValue = {
  user: null,
  status: "anonymous",
  isConfigured: false,
  signInWithGoogle: noopAsync,
  signInWithEmail: async () => ({ ok: false, message: "Sign-in is not configured." }),
  signOut: noopAsync,
};

const AuthContext = createContext<AuthContextValue>(DEFAULT_VALUE);

// Read synchronously by backend_client for every /api/me/* request.
let currentAccessToken: string | null = null;
setAccessTokenProvider(() => currentAccessToken);

function scrubAuthParamsFromUrl(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  let changed = false;
  for (const key of ["code", "state", "error", "error_description", "error_code"]) {
    if (url.searchParams.has(key)) {
      url.searchParams.delete(key);
      changed = true;
    }
  }
  if (url.hash && /(access_token|refresh_token|error)=/.test(url.hash)) {
    url.hash = "";
    changed = true;
  }
  if (changed) {
    window.history.replaceState(window.history.state, "", `${url.pathname}${url.search}${url.hash}`);
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const configured = isAuthConfigured();

  const [user, setUser] = useState<AuthUser | null>(null);
  const [status, setStatus] = useState<AuthStatus>(configured ? "loading" : "anonymous");
  const lastUserIdRef = useRef<string | null>(null);

  useEffect(() => {
    const supabase = getSupabase();
    if (!supabase) {
      setStatus("anonymous");
      return;
    }

    const applySession = (session: { access_token?: string; user?: { id: string; email?: string | null } } | null) => {
      currentAccessToken = session?.access_token ?? null;
      const nextId = session?.user?.id ?? null;

      // Identity boundary: wipe every cached query so user B never sees user A's data.
      if (nextId !== lastUserIdRef.current) {
        lastUserIdRef.current = nextId;
        queryClient.clear();
      }

      if (nextId) {
        setUser({ id: nextId, email: session?.user?.email ?? null });
        setStatus("authenticated");
      } else {
        setUser(null);
        setStatus("anonymous");
      }
    };

    let active = true;
    supabase.auth.getSession().then(({ data }) => {
      if (!active) return;
      applySession(data.session);
      // A callback (?code=...) has been consumed by supabase-js by now; tidy the URL.
      scrubAuthParamsFromUrl();
    });

    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      if (active) applySession(session);
    });

    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [queryClient]);

  const signInWithGoogle = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    await supabase.auth.signInWithOAuth({
      provider: "google",
      // Return to exactly where the user was - research state in the URL is preserved.
      options: { redirectTo: window.location.href },
    });
  }, []);

  const signInWithEmail = useCallback(async (email: string) => {
    const supabase = getSupabase();
    if (!supabase) return { ok: false, message: "Sign-in is not configured." };
    const trimmed = email.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(trimmed)) {
      return { ok: false, message: "Enter a valid email address." };
    }
    const { error } = await supabase.auth.signInWithOtp({
      email: trimmed,
      options: { emailRedirectTo: window.location.href },
    });
    if (error) return { ok: false, message: error.message };
    return { ok: true, message: "Check your email for a sign-in link." };
  }, []);

  const signOut = useCallback(async () => {
    const supabase = getSupabase();
    if (!supabase) return;
    await supabase.auth.signOut();
    // onAuthStateChange(SIGNED_OUT) -> applySession(null) -> queryClient.clear() + anon.
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ user, status, isConfigured: configured, signInWithGoogle, signInWithEmail, signOut }),
    [user, status, configured, signInWithGoogle, signInWithEmail, signOut]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}

/** Test seam. */
export function __setAccessTokenForTests(token: string | null): void {
  currentAccessToken = token;
}
