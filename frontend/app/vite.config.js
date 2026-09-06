import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Backend services run as separate processes on their own ports (see
// scripts/run_stack.sh). Proxying keeps the browser on one origin so we never
// depend on CORS behaving in a demo.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    // Without strictPort, a second `npm run dev` silently binds the NEXT free
    // port while still printing "Local: http://localhost:5174/". The browser
    // then talks to whichever server won the race and its HMR socket wedges —
    // which shows up as a blank page, not an error. Fail loudly instead.
    strictPort: true,
    proxy: {
      '/api/auth':      { target: 'http://localhost:8004', changeOrigin: true, rewrite: p => p.replace(/^\/api\/auth/, '') },
      '/api/inventory': { target: 'http://localhost:8000', changeOrigin: true, rewrite: p => p.replace(/^\/api\/inventory/, '') },
      '/api/feedback':  { target: 'http://localhost:8002', changeOrigin: true, rewrite: p => p.replace(/^\/api\/feedback/, '') },
      '/api/pricing':   { target: 'http://localhost:8003', changeOrigin: true, rewrite: p => p.replace(/^\/api\/pricing/, '') },
      '/api/agent':     { target: 'http://localhost:8005', changeOrigin: true, rewrite: p => p.replace(/^\/api\/agent/, '') },
    },
  },
})
