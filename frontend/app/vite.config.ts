// vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [
    tanstackRouter({
      target: 'react',
      autoCodeSplitting: true, // 2026 standard for TanStack
    }),
    tailwindcss(), // Tailwind v4 replaces PostCSS
    react()
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
  server: {
    // 5173 is left to legacy-app so both can run side by side during the port.
    port: 5174,
    proxy: {
      // Each backend service is a separate process on its own port. The client
      // calls relative /api/* paths so there is no CORS in dev and the same
      // paths work behind a load balancer in production.
      //
      // NOTE: auth/agent/inventory mount their routers under their own prefix,
      // so the full path legitimately repeats the segment:
      //   /api/auth/auth/login, /api/agent/agent/runs, /api/inventory/inventory
      "/api/auth": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/auth/, ""),
      },
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
      "/api/agent": {
        target: "http://127.0.0.1:8003",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/agent/, ""),
      },
      "/api/pricing": {
        target: "http://127.0.0.1:8004",
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/api\/pricing/, ""),
      },
    },
  },
})