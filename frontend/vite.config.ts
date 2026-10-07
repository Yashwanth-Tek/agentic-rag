/// <reference types="vitest/config" />
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The API runs separately (uvicorn on 8010). The dev server proxies /api to it, so the browser
// talks to a single origin and the backend needs no CORS configuration.
const apiUrl = process.env.API_URL ?? 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '127.0.0.1',
    port: 5174,
    proxy: { '/api': apiUrl },
  },
  test: {
    environment: 'node',
    include: ['src/**/*.test.ts'],
  },
})
