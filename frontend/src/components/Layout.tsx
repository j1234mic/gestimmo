import { useState, useEffect } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  LayoutDashboard,
  Building2,
  Users,
  UserCheck,
  FileText,
  Wallet,
  Wrench,
  Building,
  Kanban,
  BarChart3,
  MessageSquare,
  FolderOpen,
  Shield,
  MapPin,
  LogOut,
  Menu,
  X,
  Home,
  Settings,
  Bell,
  Search,
  Database,
  Zap,
} from 'lucide-react'
import { useAuthStore } from '../store/authStore'
import { API_BASE_URL } from '../api/client'

const navigation = [
  { name: 'Tableau de bord', href: '/', icon: LayoutDashboard },
  { name: 'Biens', href: '/properties', icon: Building2 },
  { name: 'Propriétaires', href: '/owners', icon: Users },
  { name: 'Locataires', href: '/tenants', icon: UserCheck },
  { name: 'Baux', href: '/leases', icon: FileText },
  { name: 'Finance', href: '/finance', icon: Wallet },
  { name: 'Maintenance', href: '/maintenance', icon: Wrench },
  { name: 'Copropriété', href: '/condo', icon: Building },
  { name: 'CRM', href: '/crm', icon: Kanban },
  { name: 'Reporting', href: '/reporting', icon: BarChart3 },
  { name: 'Communication', href: '/comms', icon: MessageSquare },
  { name: 'GED', href: '/ged', icon: FolderOpen },
  { name: 'Carte', href: '/geolocation', icon: MapPin },
  { name: 'Extension (18-31)', href: '/extension', icon: Zap },
  { name: 'Admin & Sécurité', href: '/admin', icon: Shield },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()

  // Fermer sidebar sur changement de route mobile
  useEffect(() => {
    setSidebarOpen(false)
  }, [location.pathname])

  const handleLogout = async () => {
    await logout()
    navigate('/login')
  }

  return (
    <div className="min-h-screen bg-slate-50">
      {/* Sidebar mobile overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 bg-slate-900/50 lg:hidden" onClick={() => setSidebarOpen(false)} />
      )}

      {/* Sidebar */}
      <div className={`fixed inset-y-0 left-0 z-50 w-72 bg-white border-r border-slate-200 transform transition-transform duration-200 ease-in-out lg:translate-x-0 ${sidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="flex h-full flex-col">
          {/* Logo */}
          <div className="flex h-16 items-center gap-3 border-b border-slate-200 px-6">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-600 text-white font-bold text-lg">G</div>
            <div>
              <div className="font-semibold text-slate-900">GestImmo</div>
              <div className="text-xs text-slate-500">v{import.meta.env.VITE_APP_VERSION || '1.2.0'}</div>
            </div>
            <button onClick={() => setSidebarOpen(false)} className="ml-auto lg:hidden p-2 rounded-lg hover:bg-slate-100">
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* API Badge */}
          <div className="px-4 py-3">
            <div className="rounded-lg bg-slate-50 border border-slate-200 p-3">
              <div className="flex items-center gap-2 text-xs font-medium text-slate-700">
                <Database className="h-3.5 w-3.5" />
                API Base
              </div>
              <div className="mt-1 font-mono text-[11px] text-slate-600 break-all">
                {API_BASE_URL} {API_BASE_URL === '/api' && <span className="text-emerald-600">(proxy → :8000)</span>}
              </div>
              <div className="mt-2 text-[11px] text-slate-500">
                Proxy Vite: <span className="font-mono">/api → http://localhost:8000</span>
              </div>
            </div>
          </div>

          {/* Navigation */}
          <nav className="flex-1 overflow-y-auto px-3 py-2 space-y-1">
            {navigation.map((item) => {
              const isActive = location.pathname === item.href || (item.href !== '/' && location.pathname.startsWith(item.href))
              return (
                <Link
                  key={item.name}
                  to={item.href}
                  className={`group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors ${
                    isActive ? 'bg-brand-50 text-brand-700 border border-brand-200' : 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'
                  }`}
                >
                  <item.icon className={`h-5 w-5 ${isActive ? 'text-brand-600' : 'text-slate-400 group-hover:text-slate-600'}`} />
                  {item.name}
                </Link>
              )
            })}
          </nav>

          {/* User */}
          <div className="border-t border-slate-200 p-4">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-full bg-slate-200 flex items-center justify-center text-sm font-medium text-slate-700">
                {user?.full_name?.[0] || user?.email?.[0] || 'U'}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-slate-900 truncate">{user?.full_name || 'Utilisateur'}</div>
                <div className="text-xs text-slate-500 truncate">{user?.email}</div>
              </div>
              <button onClick={handleLogout} className="p-2 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-slate-700" title="Déconnexion">
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Main content */}
      <div className="lg:pl-72">
        {/* Top bar */}
        <div className="sticky top-0 z-30 flex h-16 items-center gap-4 border-b border-slate-200 bg-white/80 backdrop-blur px-4 lg:px-8">
          <button onClick={() => setSidebarOpen(true)} className="lg:hidden p-2 rounded-xl hover:bg-slate-100">
            <Menu className="h-5 w-5" />
          </button>

          <div className="flex-1 flex items-center gap-3">
            <div className="hidden md:flex items-center gap-2 text-sm text-slate-500">
              <Home className="h-4 w-4" />
              <span>/</span>
              <span className="text-slate-900 font-medium capitalize">{location.pathname.split('/')[1] || 'dashboard'}</span>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="hidden md:flex items-center gap-2 rounded-full bg-slate-100 px-3 py-1.5 text-xs">
              <div className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              Backend :8000
            </div>
            <button className="p-2 rounded-xl hover:bg-slate-100 text-slate-500">
              <Search className="h-5 w-5" />
            </button>
            <button className="p-2 rounded-xl hover:bg-slate-100 text-slate-500">
              <Bell className="h-5 w-5" />
            </button>
            <button className="p-2 rounded-xl hover:bg-slate-100 text-slate-500">
              <Settings className="h-5 w-5" />
            </button>
          </div>
        </div>

        {/* Page content */}
        <main className="p-4 lg:p-8">{children}</main>
      </div>
    </div>
  )
}
