import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  BackendClient,
  AuthRequiredError,
  setAccessTokenProvider,
} from "@/data/backend/backend_client";
import { mapItemsToServer } from "@/data/watchlist/use_server_watchlist";
import type { WatchlistItem } from "@/domain/models";

function jsonResponse(body: unknown, init: Partial<Response> = {}) {
  return {
    ok: (init.status ?? 200) < 400,
    status: init.status ?? 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
  vi.stubGlobal("fetch", fetchMock);
  setAccessTokenProvider(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
  setAccessTokenProvider(null);
});

describe("backend client - Authorization is attached ONLY to /api/me/*", () => {
  it("public market history carries no Authorization header even when a token exists", async () => {
    setAccessTokenProvider(() => "tok-should-not-be-used");
    const client = new BackendClient("http://api.test");
    await client.getMarketHistory("HPG", "1D");
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBeUndefined();
  });

  it("protected watchlist GET attaches the current bearer token", async () => {
    setAccessTokenProvider(() => "tok-abc");
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [], updatedAt: null, source: "server" }));
    const client = new BackendClient("http://api.test");
    await client.getMyWatchlist();
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("http://api.test/api/me/watchlist");
    expect(init.headers.Authorization).toBe("Bearer tok-abc");
  });

  it("protected PUT sends the item list as JSON with the token", async () => {
    setAccessTokenProvider(async () => "tok-xyz");
    fetchMock.mockResolvedValueOnce(jsonResponse({ items: [{ symbol: "HPG" }] }));
    const client = new BackendClient("http://api.test");
    await client.putMyWatchlist([{ symbol: "HPG", notes: "note" }]);
    const [, init] = fetchMock.mock.calls[0];
    expect(init.method).toBe("PUT");
    expect(init.headers.Authorization).toBe("Bearer tok-xyz");
    expect(JSON.parse(init.body)).toEqual({ items: [{ symbol: "HPG", notes: "note" }] });
  });

  it("a protected call with no session throws AuthRequiredError and never calls fetch", async () => {
    setAccessTokenProvider(() => null);
    const client = new BackendClient("http://api.test");
    await expect(client.getMyWatchlist()).rejects.toBeInstanceOf(AuthRequiredError);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("a 401 from the backend surfaces as AuthRequiredError (no retry loop)", async () => {
    setAccessTokenProvider(() => "tok-expired");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unauthorized" }, { status: 401 }));
    const client = new BackendClient("http://api.test");
    const err = await client.getMyWatchlist().catch((e) => e);
    expect(err).toBeInstanceOf(AuthRequiredError);
    expect(err.status).toBe(401);
    expect(err.message).toMatch(/HTTP 401/); // matches the shared no-retry predicate
  });

  it("a 403 from the backend also surfaces as AuthRequiredError", async () => {
    setAccessTokenProvider(() => "tok");
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "forbidden" }, { status: 403 }));
    const client = new BackendClient("http://api.test");
    const err = await client.getMyWatchlist().catch((e) => e);
    expect(err).toBeInstanceOf(AuthRequiredError);
    expect(err.status).toBe(403);
  });
});

describe("mapItemsToServer - only user-owned fields leave the browser", () => {
  it("sends symbol + notes and drops all instrument/reference metadata", () => {
    const item: WatchlistItem = {
      symbol: "ctcb2601",
      instrumentType: "CW",
      underlyingSymbol: "TCB",
      issuer: "SPOOFED",
      strikePrice: 999999,
      exerciseRatio: 42,
      maturityDate: "2099-01-01",
      lastTradingDate: "2099-01-01",
      addedAt: 0,
      notes: "my thesis",
    };
    expect(mapItemsToServer([item])).toEqual([{ symbol: "CTCB2601", notes: "my thesis" }]);
  });

  it("notes default to null when absent", () => {
    expect(mapItemsToServer([{ symbol: "HPG", instrumentType: "STOCK", addedAt: 0 }])).toEqual([
      { symbol: "HPG", notes: null },
    ]);
  });
});
