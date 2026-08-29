import { API_BASE_URL } from '../api/client'

/**
 * Hook utilitaire pour exposer la config API
 * - API base: (proxy relatif → /api)
 * - Proxy target: http://localhost:8000
 * - Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS)
 */
export function useApiConfig() {
  const isProxy = API_BASE_URL === '/api'
  return {
    baseUrl: API_BASE_URL,
    isProxy,
    proxyTarget: 'http://localhost:8000',
    isDev: import.meta.env.DEV,
    appName: import.meta.env.VITE_APP_NAME || 'GestImmo',
    version: import.meta.env.VITE_APP_VERSION || '1.2.0',
    docsUrl: isProxy ? 'http://localhost:8000/docs' : `${API_BASE_URL.replace(/\/api\/?$/, '')}/docs`,
  }
}
