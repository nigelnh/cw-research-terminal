import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
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
      // SSI iboard proxy — avoids browser CORS restrictions.
      // Browser calls /api/ssi/stock-info?... → Vite dev server forwards to SSI.
      // changeOrigin rewrites the Host header so SSI accepts the request.
      "/api/ssi": {
        target: "https://iboard-api.ssi.com.vn",
        changeOrigin: true,
        secure: false,
        rewrite: (path) => path.replace(/^\/api\/ssi/, "/statistics/company/ssmi"),
        headers: {
          "Referer": "https://iboard.ssi.com.vn/",
          "Origin": "https://iboard.ssi.com.vn",
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
          "Accept": "application/json, text/plain, */*",
          "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        },
      },
    },
  },
});

