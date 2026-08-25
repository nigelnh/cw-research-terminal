import { describe, it, expect } from "vitest";
import { resolveAppConfig } from "../config";

describe("Production Configuration Hardening & Validation", () => {
  it("1. Mock mode in development sets empty backend URLs with zero config error", () => {
    const conf = resolveAppConfig({ VITE_DATA_MODE: "mock" }, false);
    expect(conf.dataMode).toBe("mock");
    expect(conf.wsUrl).toBe("");
    expect(conf.apiUrl).toBe("");
    expect(conf.configError).toBeNull();
  });

  it("2. Mock mode in production never attempts localhost and has zero config error", () => {
    const conf = resolveAppConfig({ VITE_DATA_MODE: "mock" }, true);
    expect(conf.dataMode).toBe("mock");
    expect(conf.wsUrl).toBe("");
    expect(conf.apiUrl).toBe("");
    expect(conf.configError).toBeNull();
  });

  it("3. Live mode in development defaults safely to localhost:8501", () => {
    const conf = resolveAppConfig({ VITE_DATA_MODE: "live" }, false);
    expect(conf.dataMode).toBe("live");
    expect(conf.wsUrl).toBe("ws://localhost:8501/ws/market");
    expect(conf.apiUrl).toBe("http://localhost:8501");
    expect(conf.configError).toBeNull();
  });

  it("4. Live mode in production fails with clear error if backend URLs are missing", () => {
    const conf = resolveAppConfig({ VITE_DATA_MODE: "live" }, true);
    expect(conf.dataMode).toBe("live");
    expect(conf.configError).toContain("Production live mode requires explicit non-localhost");
  });

  it("5. Live mode in production fails with clear error if backend URLs point to localhost", () => {
    const conf = resolveAppConfig(
      {
        VITE_DATA_MODE: "live",
        VITE_MARKET_DATA_WS_URL: "ws://localhost:8787",
        VITE_MARKET_DATA_REST_URL: "http://localhost:8000",
      },
      true
    );
    expect(conf.dataMode).toBe("live");
    expect(conf.configError).toContain("Production live mode requires explicit non-localhost");
  });

  it("6. Live mode in production succeeds when configured with valid remote URLs", () => {
    const conf = resolveAppConfig(
      {
        VITE_DATA_MODE: "live",
        VITE_MARKET_DATA_WS_URL: "wss://api.research.internal/ws",
        VITE_MARKET_DATA_REST_URL: "https://api.research.internal/api",
      },
      true
    );
    expect(conf.dataMode).toBe("live");
    expect(conf.wsUrl).toBe("wss://api.research.internal/ws");
    expect(conf.apiUrl).toBe("https://api.research.internal/api");
    expect(conf.configError).toBeNull();
  });
});
