// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createElement, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor, act } from "@testing-library/react";

// ---- fake Supabase (the only auth SDK seam) -------------------------------
type Session = { access_token: string; user: { id: string; email?: string | null } } | null;
let listeners: Array<(e: string, s: Session) => void> = [];
let currentSession: Session = null;
const oauth = vi.fn(async () => ({ data: {}, error: null }));
const otp = vi.fn(async () => ({ data: {}, error: null }));

function emitSession(s: Session) {
  currentSession = s;
  listeners.forEach((l) => l(s ? "SIGNED_IN" : "SIGNED_OUT", s));
}

const fakeSupabase = {
  auth: {
    getSession: vi.fn(async () => ({ data: { session: currentSession } })),
    onAuthStateChange: vi.fn((cb: (e: string, s: Session) => void) => {
      listeners.push(cb);
      return { data: { subscription: { unsubscribe: () => (listeners = listeners.filter((l) => l !== cb)) } } };
    }),
    signInWithOAuth: oauth,
    signInWithOtp: otp,
    signOut: vi.fn(async () => {
      emitSession(null);
      return { error: null };
    }),
  },
};

vi.mock("@/data/auth/supabase_client", () => ({
  isAuthConfigured: () => true,
  getSupabase: () => fakeSupabase,
  __resetSupabaseForTests: () => {},
}));

// ---- fake backend watchlist endpoints + market provider ------------------
const { getMyWatchlist, putMyWatchlist, syncSubscriptions } = vi.hoisted(() => ({
  getMyWatchlist: vi.fn(),
  putMyWatchlist: vi.fn(),
  syncSubscriptions: vi.fn(),
}));

vi.mock("@/data/backend/backend_client", async (orig) => {
  const actual = (await orig()) as Record<string, unknown>;
  return { ...actual, backendClient: { getMyWatchlist, putMyWatchlist } };
});

vi.mock("@/data/providers", () => ({
  providers: {
    marketData: {
      getCapabilities: () => ({ maxRealtimeSymbols: 33 }),
      syncSubscriptions,
      subscribeSymbols: vi.fn(),
      connect: vi.fn(),
    },
  },
}));

import { AuthProvider, useAuth } from "@/data/auth";
import { useWatchlist, resetWatchlistMemoryForTests } from "@/data/watchlist";
import { queryKeys } from "@/data/query/query_keys";
import { WATCHLIST_STORAGE_KEY_V3, createDefaultWatchlist } from "@/domain/models";

function serverItem(symbol: string) {
  return { symbol, instrumentType: "STOCK" };
}

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  const Wrapper = ({ children }: { children: ReactNode }) =>
    createElement(QueryClientProvider, { client: qc }, createElement(AuthProvider, null, children));
  return { qc, Wrapper };
}

/**
 * Render `useWatchlist` and wait until the AuthProvider mount effect has run and
 * subscribed (source resolves to "anonymous"), so a later `emitSession` is observed.
 */
async function renderResolvedWatchlist(Wrapper: (p: { children: ReactNode }) => JSX.Element) {
  const view = renderHook(() => useWatchlist(), { wrapper: Wrapper });
  await waitFor(() => expect(view.result.current.source).toBe("anonymous"));
  return view;
}

const A: Session = { access_token: "tok-a", user: { id: "user-a", email: "a@example.com" } };
const B: Session = { access_token: "tok-b", user: { id: "user-b", email: "b@example.com" } };

beforeEach(() => {
  listeners = [];
  currentSession = null;
  getMyWatchlist.mockReset();
  putMyWatchlist.mockReset();
  syncSubscriptions.mockReset();
  oauth.mockClear();
  try {
    window.localStorage.clear();
  } catch {
    /* ignore */
  }
  window.history.replaceState(null, "", "/");
  resetWatchlistMemoryForTests(createDefaultWatchlist()); // 5 primary defaults
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("anonymous", () => {
  it("uses the localStorage watchlist and never calls the server", async () => {
    const { Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);
    expect(result.current.items.length).toBe(5);
    expect(getMyWatchlist).not.toHaveBeenCalled();
    // the anonymous store persists to the versioned localStorage key
    result.current.addToWatchlist({ symbol: "SSI", instrumentType: "STOCK" });
    await waitFor(() => expect(window.localStorage.getItem(WATCHLIST_STORAGE_KEY_V3)).toBeTruthy());
  });

  it("SubscriptionPlanner receives the anonymous list", async () => {
    const { Wrapper } = makeWrapper();
    await renderResolvedWatchlist(Wrapper);
    await waitFor(() => expect(syncSubscriptions).toHaveBeenCalled());
    const lastCall = syncSubscriptions.mock.calls[syncSubscriptions.mock.calls.length - 1][0] as string[];
    expect(lastCall).toEqual(expect.arrayContaining(["HPG", "VHM"]));
  });
});

describe("authenticated watchlist", () => {
  it("loads the ordered list from the server", async () => {
    getMyWatchlist.mockResolvedValue([serverItem("FPT"), serverItem("MWG")]);
    const { Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);
    await act(async () => emitSession(A));
    await waitFor(() => expect(result.current.source).toBe("server"));
    expect(result.current.items.map((i) => i.symbol)).toEqual(["FPT", "MWG"]);
    expect(putMyWatchlist).not.toHaveBeenCalled();
  });

  it("SubscriptionPlanner switches to the resolved server list", async () => {
    getMyWatchlist.mockResolvedValue([serverItem("FPT"), serverItem("SSI")]);
    const { Wrapper } = makeWrapper();
    await renderResolvedWatchlist(Wrapper);
    await act(async () => emitSession(A));
    await waitFor(() => {
      const last = syncSubscriptions.mock.calls[syncSubscriptions.mock.calls.length - 1]?.[0] as string[] | undefined;
      expect(last).toEqual(expect.arrayContaining(["FPT", "SSI"]));
    });
  });

  it("first-login import: empty server + local list -> one PUT of the local list", async () => {
    getMyWatchlist.mockResolvedValue([]);
    putMyWatchlist.mockImplementation(async (items: unknown[]) => items);
    const { Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);
    await act(async () => emitSession(A));
    await waitFor(() => expect(putMyWatchlist).toHaveBeenCalledTimes(1));
    const imported = putMyWatchlist.mock.calls[0][0] as Array<{ symbol: string }>;
    expect(imported.map((i) => i.symbol)).toEqual(["HPG", "NVL", "VHM", "CTCB2601", "CVPB2615"]);
    await waitFor(() => expect(result.current.items.length).toBe(5));
  });

  it("non-empty server watchlist is NEVER overwritten by local data", async () => {
    getMyWatchlist.mockResolvedValue([serverItem("MWG")]);
    const { Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);
    await act(async () => emitSession(A));
    await waitFor(() => expect(result.current.items.map((i) => i.symbol)).toEqual(["MWG"]));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 25)); // let the import effect (not) fire
    });
    expect(putMyWatchlist).not.toHaveBeenCalled();
  });

  it("adding a symbol PUTs and updates the user-scoped query key", async () => {
    getMyWatchlist.mockResolvedValue([serverItem("FPT")]);
    putMyWatchlist.mockImplementation(async (items: unknown[]) => items);
    const { qc, Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);
    await act(async () => emitSession(A));
    await waitFor(() => expect(result.current.source).toBe("server"));

    await act(async () => {
      result.current.addToWatchlist({ symbol: "HPG", instrumentType: "STOCK" });
    });
    await waitFor(() => expect(putMyWatchlist).toHaveBeenCalled());
    const cached = qc.getQueryData(queryKeys.me.watchlist("user-a")) as Array<{ symbol: string }>;
    expect(cached.map((i) => i.symbol)).toEqual(["FPT", "HPG"]);
  });
});

describe("logout + user switch + cache isolation", () => {
  it("logout clears the user cache and returns to the anonymous list", async () => {
    getMyWatchlist.mockResolvedValue([serverItem("FPT")]);
    const { qc, Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);
    await act(async () => emitSession(A));
    await waitFor(() => expect(result.current.source).toBe("server"));
    expect(qc.getQueryData(queryKeys.me.watchlist("user-a"))).toBeDefined();

    await act(async () => emitSession(null));
    await waitFor(() => expect(result.current.source).toBe("anonymous"));
    expect(result.current.items.length).toBe(5); // anon defaults, untouched
    expect(qc.getQueryData(queryKeys.me.watchlist("user-a"))).toBeUndefined(); // cleared
  });

  it("user A -> user B: A's cached rows are gone and B loads its own list", async () => {
    getMyWatchlist.mockImplementation(async () => {
      if (currentSession?.user.id === "user-a") return [serverItem("AAA1")];
      return [serverItem("BBB2"), serverItem("BBB3")];
    });
    const { qc, Wrapper } = makeWrapper();
    const { result } = await renderResolvedWatchlist(Wrapper);

    await act(async () => emitSession(A));
    await waitFor(() => expect(result.current.items.map((i) => i.symbol)).toEqual(["AAA1"]));

    await act(async () => emitSession(B));
    await waitFor(() => expect(result.current.items.map((i) => i.symbol)).toEqual(["BBB2", "BBB3"]));

    expect(qc.getQueryData(queryKeys.me.watchlist("user-a"))).toBeUndefined();
    // no AAA1 anywhere in the cache
    const allData = qc.getQueryCache().getAll().flatMap((q) => (q.state.data as Array<{ symbol: string }>) ?? []);
    expect(allData.some((i) => i.symbol === "AAA1")).toBe(false);
  });

  it("identity change also clears unrelated public cache (acceptable; correctness first)", async () => {
    getMyWatchlist.mockResolvedValue([]);
    putMyWatchlist.mockImplementation(async (i: unknown[]) => i);
    const { qc, Wrapper } = makeWrapper();
    const { result } = renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    qc.setQueryData(queryKeys.history.bars({ symbol: "HPG", timeframe: "3M", interval: "1D", adjusted: true }), [{ x: 1 }]);
    await act(async () => emitSession(A));
    await waitFor(() =>
      expect(
        qc.getQueryData(queryKeys.history.bars({ symbol: "HPG", timeframe: "3M", interval: "1D", adjusted: true }))
      ).toBeUndefined()
    );
  });
});

describe("OAuth callback", () => {
  it("scrubs code/state from the URL but keeps research state", async () => {
    window.history.replaceState(null, "", "/?tab=research&symbol=HPG&range=6M&code=abc123&state=xyz");
    const { Wrapper } = makeWrapper();
    renderHook(() => useAuth(), { wrapper: Wrapper });
    await waitFor(() => expect(window.location.search).not.toContain("code="));
    const params = new URLSearchParams(window.location.search);
    expect(params.get("tab")).toBe("research");
    expect(params.get("symbol")).toBe("HPG");
    expect(params.get("range")).toBe("6M");
    expect(params.get("state")).toBeNull();
  });
});
