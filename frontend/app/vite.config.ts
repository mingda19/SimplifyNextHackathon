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
    // No proxy: each backend is called directly on its own port (see
    // src/lib/api.ts) -- 8000 inventory, 8001 auth, 8002 feedback,
    // 8003 orchestrator/agent, 8004 price_forecaster. That makes every one
    // of those a cross-origin request, so each service needs its own CORS
    // (all five already do -- see each service's `CORSMiddleware`).
  },
})