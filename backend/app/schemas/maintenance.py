"""Schémas Pydantic du module 6 : maintenance et travaux."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.maintenance import (
    ExpenseImputation,
    MaintenanceType,
    PurchaseOrderStatus,
    QuoteStatus,
    TicketCategory,
    TicketSource,
    TicketStatus,
    TicketUrgency,
    WorkDocumentType,
    WorkProjectStatus,
)


# ---------------------------------------------------------------------------
# Prestataires
# ---------------------------------------------------------------------------
class ServiceProviderCreate(BaseModel):
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    siret: Optional[str] = None
    specialties: List[str] = Field(default_factory=list)
    intervention_zone: Optional[str] = None
    tariff_hourly: Optional[float] = None
    tariff_description: Optional[str] = None
    insurance_reference: Optional[str] = None
    insurance_expiry: Optional[date] = None
    certifications: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ServiceProviderUpdate(BaseModel):
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    siret: Optional[str] = None
    specialties: Optional[List[str]] = None
    intervention_zone: Optional[str] = None
    tariff_hourly: Optional[float] = None
    tariff_description: Optional[str] = None
    insurance_reference: Optional[str] = None
    insurance_expiry: Optional[date] = None
    certifications: Optional[List[str]] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Tickets
# ---------------------------------------------------------------------------
class TicketCreate(BaseModel):
    source: TicketSource = TicketSource.MANAGER
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    property_id: int
    lease_id: Optional[int] = None
    category: TicketCategory = TicketCategory.AUTRE
    urgency: TicketUrgency = TicketUrgency.MEDIUM
    title: str
    description: Optional[str] = None
    location: Optional[str] = None
    provider_id: Optional[int] = None
    estimated_cost: float = 0


class TicketUpdate(BaseModel):
    status: Optional[TicketStatus] = None
    urgency: Optional[TicketUrgency] = None
    category: Optional[TicketCategory] = None
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    provider_id: Optional[int] = None
    assigned_to: Optional[str] = None
    estimated_cost: Optional[float] = None
    final_cost: Optional[float] = None


class TicketStatusChange(BaseModel):
    status: TicketStatus
    note: Optional[str] = None
    changed_by: Optional[str] = None


class ProviderQuoteCreate(BaseModel):
    provider_id: int
    amount: float
    description: Optional[str] = None
    valid_until: Optional[date] = None
    status: QuoteStatus = QuoteStatus.PENDING
    attachment_url: Optional[str] = None


class QuoteStatusUpdate(BaseModel):
    status: QuoteStatus


class EvaluationCreate(BaseModel):
    provider_id: int
    rating: int = Field(..., ge=1, le=5)
    comment: Optional[str] = None
    would_reuse: bool = True
    evaluated_by: Optional[str] = None


class PurchaseOrderCreate(BaseModel):
    quote_id: Optional[int] = None
    provider_id: int
    amount: float
    description: Optional[str] = None
    planned_date: Optional[date] = None


class PurchaseOrderStatusUpdate(BaseModel):
    status: PurchaseOrderStatus


# ---------------------------------------------------------------------------
# Maintenance préventive
# ---------------------------------------------------------------------------
class PreventivePlanCreate(BaseModel):
    property_id: int
    maintenance_type: MaintenanceType
    title: Optional[str] = None
    interval_months: int = 12
    frequency_label: str = "Annuel"
    next_due_date: date
    assigned_provider_id: Optional[int] = None
    estimated_cost: float = 0
    notes: Optional[str] = None


class PreventiveTaskUpdate(BaseModel):
    status: Optional[str] = None
    completed_at: Optional[datetime] = None
    cost: Optional[float] = None
    performed_by: Optional[str] = None
    observations: Optional[str] = None


# ---------------------------------------------------------------------------
# Travaux lourds
# ---------------------------------------------------------------------------
class WorkProjectCreate(BaseModel):
    property_id: int
    title: str
    description: Optional[str] = None
    project_type: Optional[str] = None
    budget: float = 0
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    responsible: Optional[str] = None
    notes: Optional[str] = None


class WorkProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[WorkProjectStatus] = None
    budget: Optional[float] = None
    actual_cost: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    progress: Optional[float] = None
    responsible: Optional[str] = None
    notes: Optional[str] = None


class WorkPhaseCreate(BaseModel):
    name: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    progress: float = 0
    display_order: int = 0


class WorkPhaseUpdate(BaseModel):
    name: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    progress: Optional[float] = None
    display_order: Optional[int] = None


# ---------------------------------------------------------------------------
# Équipements
# ---------------------------------------------------------------------------
class EquipmentCreate(BaseModel):
    property_id: int
    name: str
    category: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_until: Optional[date] = None
    maintenance_contract: Optional[str] = None
    replacement_date: Optional[date] = None
    notes: Optional[str] = None


class EquipmentUpdate(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    serial_number: Optional[str] = None
    location: Optional[str] = None
    installation_date: Optional[date] = None
    warranty_until: Optional[date] = None
    maintenance_contract: Optional[str] = None
    replacement_date: Optional[date] = None
    notes: Optional[str] = None


class EquipmentLogCreate(BaseModel):
    log_type: str = "maintenance"
    description: str
    cost: float = 0
    ticket_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Suivi financier
# ---------------------------------------------------------------------------
class MaintenanceExpenseCreate(BaseModel):
    property_id: int
    ticket_id: Optional[int] = None
    project_id: Optional[int] = None
    amount: float
    vat_rate: float = 0
    expense_date: date
    imputation: ExpenseImputation = ExpenseImputation.OWNER
    cost_type: Optional[str] = None
    description: Optional[str] = None
    provider_name: Optional[str] = None
    invoice_reference: Optional[str] = None
    paid: bool = False


# ---------------------------------------------------------------------------
# Contrôle qualité / réception
# ---------------------------------------------------------------------------
class QualityControl(BaseModel):
    passed: bool
    comment: Optional[str] = None
    controlled_by: Optional[str] = None
