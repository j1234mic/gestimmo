import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

/**
 * GestImmo Frontend — Vite config
 *
 * API base: (proxy relatif → /api)
 * Proxy target: http://localhost:8000
 * Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS).
 * Backend attendu sur :8000 — vérifiez `docker compose up -d postgres` puis `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
 */

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const proxyTarget = env.VITE_PROXY_TARGET || 'http://localhost:8000'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      // Permet le preview e2b: https://{port}-{sandboxId}.e2b.app
      allowedHosts: true,
      cors: true,
      hmr: {
        clientPort: 443,
      },
      // Proxy relatif → /api pour éviter CORS en dev.
      // Laissez VITE_API_URL vide pour utiliser ce proxy.
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
          // conserve le préfixe /api tel quel (backend expose /api/...)
        },
        '/uploads': {
          target: proxyTarget,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    preview: {
      host: '0.0.0.0',
      port: 4173,
      allowedHosts: true,
    },
  }
})
