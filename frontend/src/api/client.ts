/**
 * Client API GestImmo
 *
 * API base: (proxy relatif → /api)
 * Proxy target: http://localhost:8000
 * Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS).
 * Backend attendu sur :8000 — vérifiez `docker compose up -d postgres` puis `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`
 *
 * Logique:
 * - Si VITE_API_URL est vide/non défini → utilise "/api" relatif (proxy Vite)
 * - Sinon utilise la valeur absolue (ex: https://api.prod.com)
 * - On normalise pour éviter double slash
 */

import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios'

// Détermination de la base URL
function getApiBaseUrl(): string {
  const envUrl = import.meta.env.VITE_API_URL?.trim()

  if (!envUrl || envUrl === '') {
    // Dev: proxy relatif → évite CORS
    // Vite proxy: /api → http://localhost:8000
    return '/api'
  }

  // Prod ou override: URL absolue
  // On s'assure qu'elle se termine sans slash pour concaténation propre
  return envUrl.replace(/\/+$/, '')
}

export const API_BASE_URL = getApiBaseUrl()

// Log de debug en dev
if (import.meta.env.DEV) {
  console.log(`[GestImmo API] Base URL: ${API_BASE_URL} ${API_BASE_URL === '/api' ? '(via Vite proxy → http://localhost:8000)' : ''}`)
}

// Instance axios principale
export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Intercepteur requête: ajoute JWT si présent
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('access_token')
    if (token && config.headers) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Gestion refresh token + erreurs globales
let isRefreshing = false
let failedQueue: Array<{
  resolve: (value?: unknown) => void
  reject: (reason?: any) => void
}> = []

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error)
    } else {
      prom.resolve(token)
    }
  })
  failedQueue = []
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // 401 → tentative de refresh
    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        // Pas de refresh possible → logout
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject })
        })
          .then((token) => {
            if (originalRequest.headers) {
              originalRequest.headers.Authorization = `Bearer ${token}`
            }
            return apiClient(originalRequest)
          })
          .catch((err) => Promise.reject(err))
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post(`${API_BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        })

        const newAccess = data.access_token
        const newRefresh = data.refresh_token

        localStorage.setItem('access_token', newAccess)
        if (newRefresh) localStorage.setItem('refresh_token', newRefresh)

        apiClient.defaults.headers.common.Authorization = `Bearer ${newAccess}`
        processQueue(null, newAccess)

        if (originalRequest.headers) {
          originalRequest.headers.Authorization = `Bearer ${newAccess}`
        }

        return apiClient(originalRequest)
      } catch (refreshError) {
        processQueue(refreshError, null)
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
        localStorage.removeItem('user')
        if (window.location.pathname !== '/login') {
          window.location.href = '/login'
        }
        return Promise.reject(refreshError)
      } finally {
        isRefreshing = false
      }
    }

    return Promise.reject(error)
  }
)

// Helper pour construire les URLs d'upload (images, docs)
// Si on est en proxy relatif, /uploads passe aussi par le proxy Vite
export function getUploadUrl(path: string): string {
  if (!path) return ''
  if (path.startsWith('http')) return path
  // Si API_BASE_URL est /api, les uploads sont servis depuis /uploads (proxy aussi)
  if (API_BASE_URL === '/api') {
    return path.startsWith('/') ? path : `/${path}`
  }
  // Si API_BASE_URL est absolue, préfixer le domaine
  const baseOrigin = API_BASE_URL.replace(/\/api\/?$/, '')
  return `${baseOrigin}${path.startsWith('/') ? '' : '/'}${path}`
}

// Wrapper typé pour les appels courants
export const api = {
  get: <T>(url: string, params?: any) => apiClient.get<T>(url, { params }).then((r) => r.data),
  post: <T>(url: string, data?: any, config?: any) => apiClient.post<T>(url, data, config).then((r) => r.data),
  put: <T>(url: string, data?: any) => apiClient.put<T>(url, data).then((r) => r.data),
  patch: <T>(url: string, data?: any) => apiClient.patch<T>(url, data).then((r) => r.data),
  delete: <T>(url: string) => apiClient.delete<T>(url).then((r) => r.data),
  upload: <T>(url: string, formData: FormData) =>
    apiClient.post<T>(url, formData, { headers: { 'Content-Type': 'multipart/form-data' } }).then((r) => r.data),
}
