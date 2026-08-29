import { useEffect, useState } from 'react'
import { Building2, Users, UserCheck, Wallet, AlertTriangle, Wrench, Calendar, TrendingUp, MapPin, Activity } from 'lucide-react'
import { dashboardApi, healthApi } from '../api/endpoints'
import type { DashboardKPIs } from '../api/types'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell } from 'recharts'
import { API_BASE_URL } from '../api/client'

export default function Dashboard() {
  const [kpis, setKpis] = useState<DashboardKPIs | null>(null)
  const [health, setHealth] = useState<any>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([dashboardApi.kpis(), healthApi.check()])
      .then(([k, h]) => {
        setKpis(k as any)
        setHealth(h)
      })
      .catch((e) => console.error(e))
      .finally(() => setLoading(false))
  }, [])

  const stats = [
    { label: 'Biens gérés', value: kpis?.total_properties ?? '-', icon: Building2, color: 'bg-blue-500' },
    { label: 'Taux occupation', value: kpis ? `${(kpis.occupancy_rate * 100 || 0).toFixed(1)}%` : '-', icon: Activity, color: 'bg-emerald-500' },
    { label: 'Revenus mensuels', value: kpis ? `${(kpis.monthly_revenue || 0).toLocaleString('fr-FR')} €` : '-', icon: Wallet, color: 'bg-amber-500' },
    { label: 'Impayés', value: kpis?.unpaid_count ?? '-', icon: AlertTriangle, color: 'bg-red-500' },
    { label: 'Tickets ouverts', value: kpis?.open_tickets ?? '-', icon: Wrench, color: 'bg-purple-500' },
    { label: 'Baux exp. 30j', value: kpis?.leases_expiring_30 ?? '-', icon: Calendar, color: 'bg-orange-500' },
  ]

  const revenueData = kpis?.revenue_last_12_months || [
    { month: 'Jan', revenue: 12000 },
    { month: 'Fév', revenue: 13500 },
    { month: 'Mar', revenue: 12800 },
    { month: 'Avr', revenue: 14200 },
    { month: 'Mai', revenue: 15500 },
    { month: 'Juin', revenue: 14800 },
  ]

  const typeData = kpis?.properties_by_type
    ? Object.entries(kpis.properties_by_type).map(([name, value]) => ({ name, value }))
    : [
        { name: 'Appartement', value: 45 },
        { name: 'Maison', value: 20 },
        { name: 'Bureau', value: 15 },
        { name: 'Commerce', value: 10 },
        { name: 'Autre', value: 10 },
      ]

  const COLORS = ['#0ea5e9', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6']

  if (loading) {
    return (
      <div className="space-y-6 animate-pulse">
        <div className="h-8 bg-slate-200 rounded w-1/3" />
        <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-6 gap-4">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-28 bg-slate-200 rounded-2xl" />
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Tableau de bord</h1>
          <p className="text-sm text-slate-500 mt-1">Vue d'ensemble temps réel • API {API_BASE_URL} • Backend :8000 • Health: {health?.status || '...'}</p>
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-xl bg-white border border-slate-200 px-3 py-2 text-xs font-mono">
            Proxy: /api → http://localhost:8000
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6 gap-4">
        {stats.map((s) => (
          <div key={s.label} className="rounded-2xl bg-white border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow">
            <div className="flex items-center justify-between">
              <div className={`h-10 w-10 rounded-xl ${s.color} flex items-center justify-center text-white`}>
                <s.icon className="h-5 w-5" />
              </div>
              <TrendingUp className="h-4 w-4 text-slate-400" />
            </div>
            <div className="mt-4">
              <div className="text-2xl font-bold">{s.value}</div>
              <div className="text-xs text-slate-500 mt-1">{s.label}</div>
            </div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 rounded-2xl bg-white border border-slate-200 p-6 shadow-sm">
          <h3 className="font-semibold mb-4">Évolution des revenus (12 mois)</h3>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={revenueData}>
                <XAxis dataKey="month" fontSize={12} />
                <YAxis fontSize={12} />
                <Tooltip />
                <Bar dataKey="revenue" fill="#0ea5e9" radius={[8, 8, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="rounded-2xl bg-white border border-slate-200 p-6 shadow-sm">
          <h3 className="font-semibold mb-4">Répartition par type</h3>
          <div className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie data={typeData} cx="50%" cy="50%" innerRadius={60} outerRadius={90} dataKey="value" label>
                  {typeData.map((_, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <div className="mt-4 space-y-2">
            {typeData.map((t, i) => (
              <div key={t.name} className="flex items-center gap-2 text-xs">
                <div className="h-3 w-3 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="flex-1">{t.name}</span>
                <span className="font-medium">{t.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Quick links / modules */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="rounded-2xl bg-gradient-to-br from-brand-600 to-brand-700 p-6 text-white">
          <MapPin className="h-6 w-6 mb-3" />
          <div className="font-semibold">Géolocalisation</div>
          <div className="text-sm text-brand-100 mt-1">Carte interactive des biens • clustering • zones</div>
        </div>
        <div className="rounded-2xl bg-white border border-slate-200 p-6">
          <div className="font-semibold">Modules 18-31</div>
          <div className="text-xs text-slate-500 mt-1">Courte durée, fiscalité, VEFA, SCPI, énergie...</div>
          <div className="mt-3 text-xs font-mono bg-slate-50 rounded p-2">/api/extension/*</div>
        </div>
        <div className="rounded-2xl bg-white border border-slate-200 p-6">
          <div className="font-semibold">Backend Stack</div>
          <div className="text-xs text-slate-500 mt-2 space-y-1">
            <div>• docker compose up -d postgres</div>
            <div>• uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload</div>
            <div>• Docs: http://localhost:8000/docs</div>
          </div>
        </div>
        <div className="rounded-2xl bg-slate-900 text-white p-6">
          <div className="font-semibold">Vite Proxy</div>
          <div className="text-xs text-slate-400 mt-2 font-mono">
            server.proxy: {'{'}<br />
            &nbsp;&nbsp;'/api': {'{'}<br />
            &nbsp;&nbsp;&nbsp;&nbsp;target: 'http://localhost:8000',<br />
            &nbsp;&nbsp;&nbsp;&nbsp;changeOrigin: true<br />
            &nbsp;&nbsp;{'}'}<br />
            {'}'}
          </div>
        </div>
      </div>
    </div>
  )
}
