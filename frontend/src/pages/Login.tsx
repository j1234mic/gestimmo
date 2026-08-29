import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Building2, Lock, Mail, AlertCircle, Database, Info } from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { API_BASE_URL } from '../api/client'

export default function Login() {
  const [email, setEmail] = useState('admin@gestimmo.local')
  const [password, setPassword] = useState('admin123')
  const [code, setCode] = useState('')
  const { login, verify2FA, isLoading, error, twoFactorRequired, clearError } = useAuthStore()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    clearError()
    try {
      if (twoFactorRequired) {
        await verify2FA(code)
      } else {
        await login(email, password)
      }
      // Si on arrive ici et que 2FA n'est plus requis → success
      if (!useAuthStore.getState().twoFactorRequired) {
        navigate('/')
      }
    } catch {
      // error géré dans store
    }
  }

  return (
    <div className="min-h-screen flex">
      {/* Left - form */}
      <div className="flex-1 flex flex-col justify-center px-6 lg:px-12 xl:px-24 bg-white">
        <div className="mx-auto w-full max-w-md">
          <div className="flex items-center gap-3 mb-10">
            <div className="h-10 w-10 rounded-xl bg-brand-600 flex items-center justify-center text-white font-bold text-xl">G</div>
            <div>
              <div className="font-bold text-xl">GestImmo</div>
              <div className="text-xs text-slate-500">Gestion Immobilière • API v1.2.0</div>
            </div>
          </div>

          <h1 className="text-3xl font-bold tracking-tight text-slate-900">Connexion</h1>
          <p className="mt-2 text-sm text-slate-600">Accédez à votre espace de gestion immobilière</p>

          {/* API info */}
          <div className="mt-6 rounded-xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex gap-2 text-xs font-semibold text-slate-700">
              <Database className="h-4 w-4" /> Configuration API
            </div>
            <div className="mt-2 space-y-1 text-[12px] font-mono text-slate-600">
              <div>API base: <span className="font-bold">{API_BASE_URL}</span> {API_BASE_URL === '/api' ? '(proxy relatif → /api)' : ''}</div>
              <div>Proxy target: <span className="font-bold">http://localhost:8000</span></div>
              <div className="flex gap-1 items-start text-[11px] text-slate-500 pt-1">
                <Info className="h-3 w-3 mt-0.5 flex-shrink-0" />
                Astuce: laissez VITE_API_URL vide en dev pour utiliser le proxy Vite (évite CORS).
              </div>
            </div>
          </div>

          {error && (
            <div className="mt-6 rounded-xl bg-red-50 border border-red-200 p-4 flex gap-3 text-sm text-red-800">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div className="break-all">{error}</div>
            </div>
          )}

          <form onSubmit={handleSubmit} className="mt-8 space-y-5">
            {!twoFactorRequired ? (
              <>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1.5">Email</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                    <input
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 bg-white pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
                      placeholder="admin@gestimmo.local"
                      required
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-700 mb-1.5">Mot de passe</label>
                  <div className="relative">
                    <Lock className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      className="w-full rounded-xl border border-slate-200 bg-white pl-10 pr-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
                      placeholder="••••••••"
                      required
                    />
                  </div>
                </div>
              </>
            ) : (
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1.5">Code 2FA</label>
                <input
                  type="text"
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  className="w-full rounded-xl border border-slate-200 bg-white px-4 py-2.5 text-sm tracking-widest text-center font-mono focus:outline-none focus:ring-2 focus:ring-brand-500"
                  placeholder="123456"
                  autoFocus
                />
                <p className="mt-2 text-xs text-slate-500">Code envoyé par { /* method */ } – vérifiez vos logs si ENV=development</p>
              </div>
            )}

            <button
              type="submit"
              disabled={isLoading}
              className="w-full rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow hover:bg-brand-700 focus:outline-none focus:ring-2 focus:ring-brand-500 focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isLoading ? 'Connexion...' : twoFactorRequired ? 'Vérifier le code' : 'Se connecter'}
            </button>

            <div className="text-xs text-slate-500 space-y-1 pt-2">
              <div>Backend attendu sur :8000 — vérifiez :</div>
              <div className="font-mono bg-slate-100 rounded px-2 py-1">docker compose up -d postgres</div>
              <div className="font-mono bg-slate-100 rounded px-2 py-1">uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload</div>
            </div>
          </form>

          <div className="mt-8 text-xs text-slate-400">
            <div>Comptes de test (après bootstrap) :</div>
            <div className="mt-1 font-mono bg-slate-50 border rounded p-2">
              admin@gestimmo.local / admin123<br />
              ou via POST /api/auth/login
            </div>
          </div>
        </div>
      </div>

      {/* Right - hero */}
      <div className="hidden lg:flex flex-1 bg-slate-900 relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-600/20 via-slate-900 to-slate-900" />
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_30%_20%,rgba(14,165,233,0.15),transparent_50%)]" />
        <div className="relative z-10 flex flex-col justify-between p-12 text-white w-full">
          <div />
          <div>
            <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-xs backdrop-blur">
              <div className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
              API 670 routes • 209 modèles • 95 tests verts
            </div>
            <h2 className="mt-6 text-4xl font-bold leading-tight">L'API immobilière la plus complète</h2>
            <p className="mt-4 text-slate-300 text-sm leading-relaxed max-w-md">
              31 modules : biens, propriétaires, locataires, baux, finance, maintenance, copro, CRM, reporting, GED, géoloc, IA, extensions courte durée, fiscalité, VEFA, SCPI...
            </p>
            <div className="mt-8 grid grid-cols-2 gap-3 text-xs">
              <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                <div className="font-semibold">Proxy Vite</div>
                <div className="mt-1 font-mono text-slate-300">/api → :8000</div>
                <div className="text-[11px] text-slate-400">évite CORS en dev</div>
              </div>
              <div className="rounded-xl bg-white/5 border border-white/10 p-3">
                <div className="font-semibold">Base URL</div>
                <div className="mt-1 font-mono text-slate-300">VITE_API_URL=''</div>
                <div className="text-[11px] text-slate-400">relatif = proxy</div>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-400">
            <Building2 className="h-4 w-4" />
            GestImmo © 2026 — FastAPI + Vite + React
          </div>
        </div>
      </div>
    </div>
  )
}
