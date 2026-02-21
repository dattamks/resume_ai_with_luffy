import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Proxy /api calls to Django during development.
      // In production, Django serves both the build and the API — no proxy needed.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    // Assets land in dist/assets/ — Django's STATICFILES_DIRS points there.
    assetsDir: 'assets',
  },
})
