import { useEffect, useState } from 'react'
import { apiClient, API_BASE_URL } from '../api/client'
import { Database, ExternalLink, Code, Info } from 'lucide-react'

interface Props {
  title: string
  module: string
  apiPath: string
  description: string
}

export default function GenericModule({ title, module, apiPath, description }: Props) {
  const [data, setData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    apiClient.get(apiPath)
      .then(r => setData(r.data))
      .catch(e => setError(e.response?.data?.detail || e.message))
      .finally(() => setLoading(false))
  }, [apiPath])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">{title}</h1>
        <p className="text-sm text-slate-500 mt-1">{module} • {description}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-2xl bg-white border border-slate-200 p-6">
          <h3 className="font-semibold flex items-center gap-2">
            <Database className="h-4 w-4" /> Données API
          </h3>
          <div className="mt-2 text-xs font-mono bg-slate-50 border rounded px-3 py-2">
            GET {API_BASE_URL}{apiPath} <span className="text-slate-400">→ proxy Vite → http://localhost:8000{apiPath}</span>
          </div>

          <div className="mt-4">
            {loading ? (
              <div className="animate-pulse space-y-3">
                <div className="h-4 bg-slate-200 rounded w-3/4" />
                <div className="h-4 bg-slate-200 rounded w-1/2" />
                <div className="h-32 bg-slate-200 rounded" />
              </div>
            ) : error ? (
              <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 text-sm text-amber-800">
                <div className="font-medium flex items-center gap-2"><Info className="h-4 w-4" /> Backend non joignable ou route vide</div>
                <div className="mt-2 font-mono text-xs break-all">{error}</div>
                <div className="mt-3 text-xs">
                  Vérifiez:
                  <ul className="list-disc ml-5 mt-1 space-y-1">
                    <li><span className="font-mono">docker compose up -d postgres</span> (depuis backend/)</li>
                    <li><span className="font-mono">uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload</span></li>
                    <li>Docs: <a href="http://localhost:8000/docs" target="_blank" className="underline">http://localhost:8000/docs</a></li>
                  </ul>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="text-xs text-slate-500">{Array.isArray(data) ? `${data.length} éléments` : typeof data === 'object' ? `${Object.keys(data).length} clés` : 'Réponse reçue'}</div>
                <pre className="bg-slate-900 text-slate-100 rounded-xl p-4 text-xs overflow-auto max-h-[500px]">
                  {JSON.stringify(data, null, 2).slice(0, 10000)}
                </pre>
              </div>
            )}
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-2xl bg-slate-900 text-white p-6">
            <h4 className="font-semibold text-sm">Proxy Vite (évite CORS)</h4>
            <pre className="mt-3 text-[11px] font-mono bg-white/10 rounded p-3 overflow-auto">
{`// vite.config.ts
server: {
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
    '/uploads': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    }
  }
}

// .env
VITE_API_URL=  ← vide = utilise /api relatif
`}
            </pre>
          </div>

          <div className="rounded-2xl bg-white border border-slate-200 p-6">
            <h4 className="font-semibold text-sm flex items-center gap-2"><Code className="h-4 w-4" /> Client API</h4>
            <pre className="mt-3 text-[11px] font-mono bg-slate-50 border rounded p-3 overflow-auto">
{`// src/api/client.ts
const base = import.meta.env.VITE_API_URL?.trim()
  ? import.meta.env.VITE_API_URL
  : '/api'  // ← proxy relatif

export const apiClient = axios.create({
  baseURL: base, // /api → Vite → :8000
})

// Astuce: laissez VITE_API_URL vide
// en dev pour éviter CORS
`}
            </pre>
          </div>

          <div className="rounded-2xl bg-white border border-slate-200 p-5">
            <div className="text-sm font-medium">Endpoints {module}</div>
            <div className="mt-3 space-y-2 text-xs font-mono">
              <div className="flex items-center gap-2"><span className="bg-emerald-100 text-emerald-700 px-1.5 py-0.5 rounded text-[10px]">GET</span> {apiPath}</div>
              <div className="flex items-center gap-2"><span className="bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded text-[10px]">POST</span> {apiPath}</div>
              <div className="flex items-center gap-2"><span className="bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded text-[10px]">PUT</span> {apiPath}/&#123;id&#125;</div>
              <div className="flex items-center gap-2"><span className="bg-red-100 text-red-700 px-1.5 py-0.5 rounded text-[10px]">DEL</span> {apiPath}/&#123;id&#125;</div>
            </div>
            <a href={`http://localhost:8000/docs`} target="_blank" className="mt-4 inline-flex items-center gap-1.5 text-xs text-brand-600 hover:underline">
              <ExternalLink className="h-3.5 w-3.5" /> Voir Swagger :8000/docs
            </a>
          </div>
        </div>
      </div>
    </div>
  )
}
