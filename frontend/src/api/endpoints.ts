import { api, apiClient } from './client'
import type { DashboardKPIs, Lease, Owner, Property, Tenant, User, PaginatedResponse, LoginResponse } from './types'

export const authApi = {
  login: (email: string, password: string) =>
    apiClient.post<LoginResponse>('/auth/login', { email, password }).then(r => r.data),
  verify2FA: (challenge_token: string, code: string) =>
    api.post<LoginResponse>('/auth/2fa/verify', { challenge_token, code }),
  me: () => api.get<User>('/auth/me'),
  logout: () => api.post('/auth/logout'),
  refresh: (refresh_token: string) => api.post<LoginResponse>('/auth/refresh', { refresh_token }),
}

export const propertiesApi = {
  list: (params?: any) => api.get<PaginatedResponse<Property> | Property[]>('/properties', params).then(res => {
    // Backend peut renvoyer soit {data, total} soit directement array selon route
    if (Array.isArray(res)) return { data: res, total: res.length, page: 1, limit: res.length, pages: 1 } as PaginatedResponse<Property>
    if ((res as any).data) return res as PaginatedResponse<Property>
    // fallback v2 hexagonal
    return { data: res as any, total: (res as any).length || 0, page: 1, limit: 20, pages: 1 }
  }),
  get: (id: string | number) => api.get<Property>(`/properties/${id}`),
  create: (data: Partial<Property>) => api.post<Property>('/properties', data),
  update: (id: string | number, data: Partial<Property>) => api.put<Property>(`/properties/${id}`, data),
  delete: (id: string | number) => api.delete(`/properties/${id}`),
  // v2 hexagonal
  listV2: (params?: any) => api.get<any>('/v2/properties', params),
}

export const ownersApi = {
  list: (params?: any) => api.get<any>('/owners', params),
  get: (id: string | number) => api.get<Owner>(`/owners/${id}`),
  create: (data: any) => api.post<Owner>('/owners', data),
  update: (id: string | number, data: any) => api.put<Owner>(`/owners/${id}`, data),
  delete: (id: string | number) => api.delete(`/owners/${id}`),
}

export const tenantsApi = {
  list: (params?: any) => api.get<any>('/tenants', params),
  get: (id: string | number) => api.get<Tenant>(`/tenants/${id}`),
  create: (data: any) => api.post<Tenant>('/tenants', data),
  update: (id: string | number, data: any) => api.put<Tenant>(`/tenants/${id}`, data),
}

export const leasesApi = {
  list: (params?: any) => api.get<any>('/leases', params),
  get: (id: string | number) => api.get<Lease>(`/leases/${id}`),
  create: (data: any) => api.post<Lease>('/leases', data),
}

export const dashboardApi = {
  kpis: () => api.get<DashboardKPIs>('/reporting/dashboard/kpis').catch(() => {
    // fallback si route différente
    return api.get<DashboardKPIs>('/reports/dashboard').catch(() => ({
      total_properties: 0,
      occupancy_rate: 0,
      monthly_revenue: 0,
      yearly_revenue: 0,
      unpaid_count: 0,
      open_tickets: 0,
      leases_expiring_30: 0,
      leases_expiring_60: 0,
      mandates_expiring_30: 0,
      active_prospects: 0,
    } as DashboardKPIs))
  }),
  revenueChart: () => api.get<any>('/reporting/revenue-chart').catch(() => []),
}

export const financeApi = {
  rents: (params?: any) => api.get<any>('/finance/rents', params),
  charges: (params?: any) => api.get<any>('/finance/charges', params),
}

export const maintenanceApi = {
  tickets: (params?: any) => api.get<any>('/maintenance/tickets', params),
}

export const crmApi = {
  prospects: (params?: any) => api.get<any>('/crm/prospects', params),
  visits: (params?: any) => api.get<any>('/crm/visits', params),
}

export const healthApi = {
  check: () => apiClient.get('/health').then(r => r.data).catch(() => ({ status: 'unknown' })),
}
