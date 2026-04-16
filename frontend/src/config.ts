/**
 * Frontend configuration
 * Environment variables must start with VITE_ to be exposed to the client
 */

export const config = {
  wsUrl: import.meta.env.VITE_WS_URL || "ws://localhost:8788",
  apiUrl: import.meta.env.VITE_API_URL || "http://localhost:8001/api",
};
