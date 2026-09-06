import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend services run as separate processes on their own ports
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 1. Replaced localhost with 127.0.0.1 to fix the ECONNREFUSED error
      "/api/auth": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/auth/, ""),
      },

      // 2. Added this line because your frontend was specifically requesting `/auth/...` earlier!
      "/auth": { target: "http://127.0.0.1:8001", changeOrigin: true },

      "/api/inventory": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/inventory/, ""),
      },
      "/api/feedback": {
        target: "http://127.0.0.1:8002",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/feedback/, ""),
      },

      // Pricing is a separate service on 8004.
      "/api/pricing": {
        target: "http://127.0.0.1:8004",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/pricing/, ""),
      },
      "/api/agent": {
        target: "http://127.0.0.1:8003",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/agent/, ""),
      },
    },
  },
});
