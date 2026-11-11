import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the FastAPI backend runs on :8000. Proxying /api and /auth keeps the
// browser on one origin (no CORS), the same as production, where FastAPI serves dist/.
const backend = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': backend,
      '/auth': backend,
    },
  },
})
