/**
 * Frontend configuration
 * Environment variables must start with VITE_ to be exposed to the client
 */

const getWsUrl = () => {
  const envUrl = import.meta.env.VITE_WS_URL;
  
  // If a full ws/wss URL is provided in .env, use it
  if (envUrl && (envUrl.startsWith("ws://") || envUrl.startsWith("wss://"))) {
    return envUrl;
  }
  
  // Fallback: Use current hostname with /ws mapping
  // This allows ngrok and LAN access to work automatically via the Vite proxy
  if (typeof window !== "undefined") {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    return `${protocol}//${host}/ws`;
  }
  
  return "ws://localhost:8501";
};

export const config = {
  wsUrl: getWsUrl(),
  apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8001/api",
};

