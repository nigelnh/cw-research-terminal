import { describe, it, expect } from "vitest";
import { resolveAppConfig, normalizeWsUrl, normalizeApiUrl } from "../config";

describe("Production Configuration & URL Normalization Hardening", () => {
  it("1. Default configuration in development defaults to live mode and ws://localhost:8501/ws/market", () => {
    const conf = resolveAppConfig({}, false);
    expect(conf.dataMode).toBe("live");
    expect(conf.wsUrl).toBe("ws://localhost:8501/ws/market");
    expect(conf.apiUrl).toBe("http://localhost:8501");
    expect(conf.configError).toBeNull();
  });

  it("2. Passing legacy mock mode resolves strictly to live mode without mock fallback", () => {
    const conf = resolveAppConfig({ VITE_DATA_MODE: "mock" }, false);
    expect(conf.dataMode).toBe("live");
    expect(conf.wsUrl).toBe("ws://localhost:8501/ws/market");
    expect(conf.apiUrl).toBe("http://localhost:8501");
    expect(conf.configError).toBeNull();
  });

  it("3. Bare hostname/port in VITE_WS_URL normalizes to canonical /ws/market endpoint", () => {
    const conf1 = resolveAppConfig({ VITE_WS_URL: "ws://localhost:8501" }, false);
    expect(conf1.wsUrl).toBe("ws://localhost:8501/ws/market");

    const conf2 = resolveAppConfig({ VITE_WS_URL: "ws://localhost:8501/" }, false);
    expect(conf2.wsUrl).toBe("ws://localhost:8501/ws/market");

    const conf3 = resolveAppConfig({ VITE_WS_URL: "http://localhost:8501" }, false);
    expect(conf3.wsUrl).toBe("ws://localhost:8501/ws/market");
  });

  it("4. Explicit /ws/market in VITE_WS_URL preserves path without duplicate appending", () => {
    const conf = resolveAppConfig({ VITE_WS_URL: "ws://localhost:8501/ws/market" }, false);
    expect(conf.wsUrl).toBe("ws://localhost:8501/ws/market");
  });

  it("5. Live mode in production fails with clear error if backend URLs are missing", () => {
    const conf = resolveAppConfig({ VITE_DATA_MODE: "live" }, true);
    expect(conf.dataMode).toBe("live");
    expect(conf.configError).toContain("Production live mode requires explicit non-localhost");
  });

  it("6. Live mode in production fails with clear error if backend URLs point to localhost", () => {
    const conf = resolveAppConfig(
      {
        VITE_DATA_MODE: "live",
        VITE_MARKET_DATA_WS_URL: "ws://localhost:8501/ws/market",
        VITE_MARKET_DATA_REST_URL: "http://localhost:8501",
      },
      true
    );
    expect(conf.dataMode).toBe("live");
    expect(conf.configError).toContain("Production live mode requires explicit non-localhost");
  });

  it("7. Live mode in production succeeds and normalizes valid remote URLs", () => {
    const conf = resolveAppConfig(
      {
        VITE_DATA_MODE: "live",
        VITE_MARKET_DATA_WS_URL: "wss://api.research.internal/ws/market",
        VITE_MARKET_DATA_REST_URL: "https://api.research.internal/api",
      },
      true
    );
    expect(conf.dataMode).toBe("live");
    expect(conf.wsUrl).toBe("wss://api.research.internal/ws/market");
    expect(conf.apiUrl).toBe("https://api.research.internal/api");
    expect(conf.configError).toBeNull();
  });

  it("8. URL normalizer helper unit tests", () => {
    expect(normalizeWsUrl(undefined)).toBe("ws://localhost:8501/ws/market");
    expect(normalizeWsUrl("")).toBe("ws://localhost:8501/ws/market");
    expect(normalizeWsUrl("ws://127.0.0.1:8501")).toBe("ws://127.0.0.1:8501/ws/market");
    expect(normalizeWsUrl("http://127.0.0.1:8501")).toBe("ws://127.0.0.1:8501/ws/market");
    expect(normalizeWsUrl("https://production.com/")).toBe("wss://production.com/ws/market");

    expect(normalizeApiUrl(undefined)).toBe("http://localhost:8501");
    expect(normalizeApiUrl("ws://localhost:8501/")).toBe("http://localhost:8501");
    expect(normalizeApiUrl("https://production.com/api/")).toBe("https://production.com/api");
  });
});
