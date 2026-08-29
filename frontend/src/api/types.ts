export interface User {
  id: string
  database_id: number
  email: string
  full_name: string
  role: string
  permissions: string[]
  granular_permissions?: Record<string, string[]>
  organization_ids?: number[]
  agency_ids?: number[]
  must_change_password?: boolean
}

export interface LoginResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: User
  two_factor_required?: boolean
  challenge_token?: string
  method?: string
}

export interface Property {
  id: number
  public_id?: string
  secure_id?: string
  reference: string
  title: string
  description?: string
  property_type: string
  status: string
  address: string
  city: string
  postal_code: string
  country?: string
  latitude?: number
  longitude?: number
  surface?: number
  rooms?: number
  bedrooms?: number
  bathrooms?: number
  floor?: number
  year_built?: number
  price?: number
  rent?: number
  charges?: number
  owner_id?: number
  manager_id?: number
  available_from?: string
  virtual_tour_url?: string
  is_360_available?: boolean
  tags?: string[]
  created_at?: string
  updated_at?: string
}

export interface Owner {
  id: number
  public_id?: string
  secure_id?: string
  first_name: string
  last_name: string
  email?: string
  phone?: string
  type: string
  properties_count?: number
  created_at?: string
}

export interface Tenant {
  id: number
  public_id?: string
  first_name: string
  last_name: string
  email?: string
  phone?: string
  status: string
  solvency_score?: number
  reliability_score?: number
  current_property_id?: number
  created_at?: string
}

export interface Lease {
  id: number
  public_id?: string
  property_id: number
  tenant_id: number
  lease_type: string
  status: string
  start_date: string
  end_date?: string
  rent: number
  charges?: number
  deposit?: number
  created_at?: string
}

export interface DashboardKPIs {
  total_properties: number
  occupancy_rate: number
  monthly_revenue: number
  yearly_revenue: number
  unpaid_count: number
  open_tickets: number
  leases_expiring_30: number
  leases_expiring_60: number
  mandates_expiring_30: number
  active_prospects: number
  properties_by_type?: Record<string, number>
  revenue_last_12_months?: Array<{ month: string; revenue: number }>
}

export interface PaginatedResponse<T> {
  data: T[]
  total: number
  page: number
  limit: number
  pages: number
}
