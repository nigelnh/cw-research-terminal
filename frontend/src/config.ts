/**
 * Research Platform Frontend Configuration
 * Centralized environment configuration for data modes, realtime capacity, and backend gateway connectivity.
 */

export type DataMode = "mock" | "live" | "hybrid";

export interface AppConfig {
  dataMode: DataMode;
  wsUrl: string;
  apiUrl: string;
  defaultLiveSymbols: string[];
  maxRealtimeSymbols: number | null;
  configError: string | null;
}

export function resolveAppConfig(
  env: Record<string, string | undefined> = import.meta.env,
  isProd: boolean = import.meta.env.PROD
): AppConfig {
  const modeRaw = env.VITE_DATA_MODE;
  const dataMode: DataMode = modeRaw === "live" || modeRaw === "hybrid" ? modeRaw : "mock";

  const defaultLiveSymbols = env.VITE_DEFAULT_LIVE_SYMBOLS
    ? env.VITE_DEFAULT_LIVE_SYMBOLS.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean)
    : ["VNINDEX"];

  let maxRealtimeSymbols: number | null = 33;
  const envMax = env.VITE_MAX_REALTIME_SYMBOLS;
  if (envMax !== undefined && envMax !== "") {
    if (envMax === "null" || envMax === "unlimited") {
      maxRealtimeSymbols = null;
    } else {
      const parsed = parseInt(envMax, 10);
      maxRealtimeSymbols = isNaN(parsed) ? 33 : parsed;
    }
  }

  // 1. Mock / Demo Mode: Zero external connections, no localhost requirement in prod
  if (dataMode === "mock") {
    return {
      dataMode,
      wsUrl: "",
      apiUrl: "",
      defaultLiveSymbols,
      maxRealtimeSymbols,
      configError: null,
    };
  }

  // 2. Live / Hybrid Mode:
  const rawWsUrl = env.VITE_MARKET_DATA_WS_URL || env.VITE_CW_GUI_WS_URL || env.VITE_WS_URL;
  const rawApiUrl = env.VITE_MARKET_DATA_REST_URL || env.VITE_CW_GUI_REST_URL || env.VITE_API_URL;

  let configError: string | null = null;
  let wsUrl = rawWsUrl || "";
  let apiUrl = rawApiUrl ? rawApiUrl.replace(/\/$/, "") : "";

  if (isProd) {
    const isWsMissingOrLocal = !wsUrl || wsUrl.includes("localhost") || wsUrl.includes("127.0.0.1");
    const isApiMissingOrLocal = !apiUrl || apiUrl.includes("localhost") || apiUrl.includes("127.0.0.1");

    if (isWsMissingOrLocal || isApiMissingOrLocal) {
      configError =
        "Production live mode requires explicit non-localhost VITE_MARKET_DATA_WS_URL and VITE_MARKET_DATA_REST_URL.";
      if (typeof window !== "undefined") {
        console.error(`[AppConfig Error] ${configError}`);
      }
    }
  } else {
    // In development: Allow safe localhost fallbacks
    if (!wsUrl) wsUrl = "ws://localhost:8501/ws/market";
    if (!apiUrl) apiUrl = "http://localhost:8501";
  }

  return {
    dataMode,
    wsUrl,
    apiUrl,
    defaultLiveSymbols,
    maxRealtimeSymbols,
    configError,
  };
}

export const config: AppConfig = resolveAppConfig();
