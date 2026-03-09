import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../backend/static',
    emptyOutDir: true
  },
  server: {
    port: 3000,
    allowedHosts: ['oliver-unmagnetical-softly.ngrok-free.dev'],
    proxy: {
      '/api': {
        target: 'http://localhost:5004',
        changeOrigin: true
      },
      '/video': {
        target: 'http://localhost:5004',
        changeOrigin: true
      }
    }
  }
})
