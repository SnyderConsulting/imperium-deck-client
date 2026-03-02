import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  base: '/web/',
  build: {
    outDir: '../web',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': {
        target: process.env.DECK_API_BASE_URL || 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
      '/ws': {
        target: process.env.DECK_API_BASE_URL || 'http://127.0.0.1:8765',
        ws: true,
      },
    },
  },
})
