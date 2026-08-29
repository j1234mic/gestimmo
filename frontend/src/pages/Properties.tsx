import { useEffect, useState } from 'react'
import { Building2, Search, Plus, MapPin, Bed, Bath, Square, Eye, Filter } from 'lucide-react'
import { propertiesApi } from '../api/endpoints'
import type { Property } from '../api/types'
import { API_BASE_URL } from '../api/client'

export default function Properties() {
  const [properties, setProperties] = useState<Property[]>([])
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [filterType, setFilterType] = useState('')
  const [filterStatus, setFilterStatus] = useState('')

  useEffect(() => {
    load()
  }, [])

  const load = async () => {
    setLoading(true)
    try {
      const res = await propertiesApi.list({ search, property_type: filterType || undefined, status: filterStatus || undefined })
      setProperties(res.data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  const filtered = properties.filter(p => {
    if (search && !`${p.title} ${p.city} ${p.reference}`.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Building2 className="h-7 w-7 text-brand-600" /> Biens immobiliers
          </h1>
          <p className="text-sm text-slate-500 mt-1">Module 1 • 12 types • galerie photos/vidéos • visite 360° • API {API_BASE_URL}/properties</p>
        </div>
        <button className="inline-flex items-center gap-2 rounded-xl bg-brand-600 px-4 py-2.5 text-sm font-semibold text-white shadow hover:bg-brand-700">
          <Plus className="h-4 w-4" /> Nouveau bien
        </button>
      </div>

      {/* Filters */}
      <div className="rounded-2xl bg-white border border-slate-200 p-4 flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Rechercher titre, ville, référence..."
            className="w-full rounded-xl border border-slate-200 pl-10 pr-4 py-2.5 text-sm focus:ring-2 focus:ring-brand-500 focus:border-brand-500 outline-none"
          />
        </div>
        <select value={filterType} onChange={(e) => setFilterType(e.target.value)} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm bg-white">
          <option value="">Tous types</option>
          <option value="apartment">Appartement</option>
          <option value="house">Maison</option>
          <option value="studio">Studio</option>
          <option value="villa">Villa</option>
          <option value="office">Bureau</option>
          <option value="commercial">Commerce</option>
          <option value="land_buildable">Terrain constructible</option>
        </select>
        <select value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)} className="rounded-xl border border-slate-200 px-3 py-2.5 text-sm bg-white">
          <option value="">Tous statuts</option>
          <option value="available">Disponible</option>
          <option value="rented">Loué</option>
          <option value="for_sale">À vendre</option>
          <option value="under_renovation">En rénovation</option>
        </select>
        <button onClick={load} className="inline-flex items-center gap-2 rounded-xl border border-slate-200 px-4 py-2.5 text-sm hover:bg-slate-50">
          <Filter className="h-4 w-4" /> Filtrer
        </button>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-pulse">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="h-72 bg-slate-200 rounded-2xl" />
          ))}
        </div>
      ) : (
        <>
          <div className="text-sm text-slate-500">{filtered.length} bien(s) trouvé(s) • Proxy: /api → http://localhost:8000</div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filtered.map((p) => (
              <div key={p.id} className="group rounded-2xl bg-white border border-slate-200 overflow-hidden shadow-sm hover:shadow-lg transition-all">
                <div className="aspect-[16/10] bg-slate-100 relative overflow-hidden">
                  <div className="absolute inset-0 bg-gradient-to-br from-slate-200 to-slate-300 flex items-center justify-center">
                    <Building2 className="h-12 w-12 text-slate-400" />
                  </div>
                  <div className="absolute top-3 left-3 flex gap-2">
                    <span className="rounded-full bg-white/90 backdrop-blur px-2.5 py-1 text-[11px] font-medium border">{p.property_type}</span>
                    <span className={`rounded-full px-2.5 py-1 text-[11px] font-medium ${p.status === 'available' ? 'bg-emerald-500 text-white' : p.status === 'rented' ? 'bg-blue-500 text-white' : 'bg-amber-500 text-white'}`}>{p.status}</span>
                  </div>
                  {p.is_360_available && (
                    <div className="absolute top-3 right-3 rounded-full bg-purple-600 text-white px-2.5 py-1 text-[11px] font-medium">360°</div>
                  )}
                  <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/60 to-transparent p-4">
                    <div className="text-white font-semibold">{p.title}</div>
                    <div className="text-white/80 text-xs flex items-center gap-1"><MapPin className="h-3 w-3" /> {p.city} {p.postal_code}</div>
                  </div>
                </div>
                <div className="p-4">
                  <div className="flex items-center justify-between">
                    <div className="font-mono text-xs text-slate-500">{p.reference}</div>
                    <div className="text-sm font-bold">{p.rent ? `${p.rent} €/mois` : p.price ? `${p.price.toLocaleString()} €` : 'Prix sur demande'}</div>
                  </div>
                  <div className="mt-3 flex items-center gap-4 text-xs text-slate-600">
                    {p.surface && <span className="flex items-center gap-1"><Square className="h-3.5 w-3.5" /> {p.surface} m²</span>}
                    {p.rooms && <span className="flex items-center gap-1"><Bed className="h-3.5 w-3.5" /> {p.rooms} p.</span>}
                    {p.bedrooms && <span className="flex items-center gap-1"><Bath className="h-3.5 w-3.5" /> {p.bedrooms} ch.</span>}
                  </div>
                  <div className="mt-4 flex gap-2">
                    <button className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl bg-slate-900 text-white py-2 text-xs font-medium hover:bg-slate-800">
                      <Eye className="h-3.5 w-3.5" /> Voir
                    </button>
                    <button className="rounded-xl border border-slate-200 px-3 py-2 text-xs hover:bg-slate-50">Éditer</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
          {filtered.length === 0 && (
            <div className="rounded-2xl border border-dashed border-slate-300 p-12 text-center">
              <Building2 className="h-10 w-10 mx-auto text-slate-300" />
              <div className="mt-3 font-medium">Aucun bien trouvé</div>
              <div className="text-sm text-slate-500 mt-1">Vérifiez que le backend tourne sur :8000 et que la base est peuplée</div>
              <div className="mt-4 font-mono text-xs bg-slate-100 inline-block px-3 py-1.5 rounded">GET {API_BASE_URL}/properties</div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
