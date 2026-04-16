import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(process.cwd(), "./src"),
    },
  },
  server: {
    host: true,       // Listen on all network interfaces (enables LAN access)
    port: 3001,
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
    },
    proxy: {
      "/ws": {
        target: "ws://localhost:8788",
        ws: true,
      },
    },
  },
});

