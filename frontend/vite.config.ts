import { defineConfig, createLogger } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

const logger = createLogger();
const originalError = logger.error;
logger.error = (msg, options) => {
  if (
    msg.includes("ws proxy socket error") ||
    msg.includes("ECONNRESET") ||
    msg.includes("ECONNREFUSED")
  ) {
    return;
  } else {
    originalError(msg, options);
  }
};

export default defineConfig({
  customLogger: logger,
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(process.cwd(), "./src"),
    },
  },
  server: {
    host: true,       // Listen on all network interfaces (enables LAN access)
    port: 3001,
    allowedHosts: ["unapposite-nonpurchasable-eddie.ngrok-free.dev"],
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
    },
    proxy: {
      "/ws": {
        target: "ws://localhost:8788",
        ws: true,
      },
      "/api": {
        target: "http://localhost:8788",
        changeOrigin: true,
      },
    },
  },
});

