/**
 * Research Platform Frontend Configuration
 * Centralized environment configuration for data modes, realtime capacity, and backend gateway connectivity.
 */

export type DataMode = "live" | "hybrid";

export interface AppConfig {
  dataMode: DataMode;
  wsUrl: string;
  apiUrl: string;
  defaultLiveSymbols: string[];
  maxRealtimeSymbols: number | null;
  configError: string | null;
}

/**
 * Canonical WebSocket URL normalizer.
 * Ensures the WebSocket endpoint always includes the canonical `/ws/market` route.
 */
export function normalizeWsUrl(raw?: string, fallback: string = "ws://localhost:8501/ws/market"): string {
  if (!raw || !raw.trim()) {
    return fallback;
  }
  let url = raw.trim();
  if (url.startsWith("http://")) {
    url = "ws://" + url.slice(7);
  } else if (url.startsWith("https://")) {
    url = "wss://" + url.slice(8);
  }

  // Strip trailing slashes
  url = url.replace(/\/+$/, "");

  // If the URL has no path beyond hostname/port, append /ws/market
  try {
    const parsed = new URL(url.replace(/^ws/, "http"));
    if (parsed.pathname === "" || parsed.pathname === "/") {
      url = url + "/ws/market";
    }
  } catch {
    if (!url.includes("/ws/market")) {
      url = url + "/ws/market";
    }
  }

  return url;
}

/**
 * Canonical REST API URL normalizer.
 */
export function normalizeApiUrl(raw?: string, fallback: string = "http://localhost:8501"): string {
  if (!raw || !raw.trim()) {
    return fallback;
  }
  let url = raw.trim();
  if (url.startsWith("ws://")) {
    url = "http://" + url.slice(5);
  } else if (url.startsWith("wss://")) {
    url = "https://" + url.slice(6);
  }
  return url.replace(/\/+$/, "");
}

export function resolveAppConfig(
  env: Record<string, string | undefined> = import.meta.env,
  isProd: boolean = import.meta.env.PROD
): AppConfig {
  const modeRaw = env.VITE_DATA_MODE;
  const dataMode: DataMode = modeRaw === "hybrid" ? "hybrid" : "live";

  const defaultLiveSymbols = env.VITE_DEFAULT_LIVE_SYMBOLS
    ? env.VITE_DEFAULT_LIVE_SYMBOLS.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean)
    : [];

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

  // Live Mode URL Resolution:
  const rawWsUrl = env.VITE_MARKET_DATA_WS_URL || env.VITE_CW_GUI_WS_URL || env.VITE_WS_URL;
  const rawApiUrl = env.VITE_MARKET_DATA_REST_URL || env.VITE_CW_GUI_REST_URL || env.VITE_API_URL;

  let configError: string | null = null;
  let wsUrl = "";
  let apiUrl = "";

  if (isProd) {
    wsUrl = rawWsUrl ? normalizeWsUrl(rawWsUrl, "") : "";
    apiUrl = rawApiUrl ? normalizeApiUrl(rawApiUrl, "") : "";

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
    // In development: Default to live FastAPI backend at localhost:8501
    wsUrl = normalizeWsUrl(rawWsUrl, "ws://localhost:8501/ws/market");
    apiUrl = normalizeApiUrl(rawApiUrl, "http://localhost:8501");
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
