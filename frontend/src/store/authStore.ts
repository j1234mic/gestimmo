import { create } from 'zustand'
import { authApi } from '../api/endpoints'
import type { User } from '../api/types'

interface AuthState {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  error: string | null
  twoFactorRequired: boolean
  challengeToken: string | null
  login: (email: string, password: string) => Promise<void>
  verify2FA: (code: string) => Promise<void>
  logout: () => Promise<void>
  checkAuth: () => Promise<void>
  clearError: () => void
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: false,
  error: null,
  twoFactorRequired: false,
  challengeToken: null,

  login: async (email: string, password: string) => {
    set({ isLoading: true, error: null })
    try {
      const res = await authApi.login(email, password)

      // @ts-ignore - backend peut renvoyer challenge 2FA dans login
      if ((res as any).two_factor_required) {
        set({
          twoFactorRequired: true,
          challengeToken: (res as any).challenge_token,
          isLoading: false,
        })
        return
      }

      localStorage.setItem('access_token', res.access_token)
      localStorage.setItem('refresh_token', res.refresh_token)
      localStorage.setItem('user', JSON.stringify(res.user))

      set({
        user: res.user,
        isAuthenticated: true,
        isLoading: false,
        twoFactorRequired: false,
        challengeToken: null,
      })
    } catch (err: any) {
      const message = err.response?.data?.detail || err.response?.data?.message || err.message || 'Erreur de connexion'
      const detail = typeof message === 'object' ? JSON.stringify(message) : message
      set({ error: detail, isLoading: false })
      throw err
    }
  },

  verify2FA: async (code: string) => {
    const { challengeToken } = get()
    if (!challengeToken) throw new Error('No challenge token')
    set({ isLoading: true, error: null })
    try {
      const res = await authApi.verify2FA(challengeToken, code)
      localStorage.setItem('access_token', res.access_token)
      localStorage.setItem('refresh_token', res.refresh_token)
      localStorage.setItem('user', JSON.stringify(res.user))
      set({
        user: res.user,
        isAuthenticated: true,
        isLoading: false,
        twoFactorRequired: false,
        challengeToken: null,
      })
    } catch (err: any) {
      const message = err.response?.data?.detail || err.message
      set({ error: typeof message === 'string' ? message : JSON.stringify(message), isLoading: false })
      throw err
    }
  },

  logout: async () => {
    try {
      await authApi.logout()
    } catch {}
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('user')
    set({ user: null, isAuthenticated: false, twoFactorRequired: false, challengeToken: null })
  },

  checkAuth: async () => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      set({ isAuthenticated: false, user: null })
      return
    }
    try {
      const user = await authApi.me()
      // @ts-ignore - /me peut renvoyer {email, role} ou full user
      const normalized = (user as any).email ? (user as any) : (user as any).user || JSON.parse(localStorage.getItem('user') || 'null')
      if (normalized) {
        localStorage.setItem('user', JSON.stringify(normalized))
        set({ user: normalized, isAuthenticated: true })
      }
    } catch {
      // token invalide → on laisse l'intercepteur gérer le refresh, sinon logout
      // ne pas logout immédiatement pour laisser le refresh tenter
    }
  },

  clearError: () => set({ error: null }),
}))
