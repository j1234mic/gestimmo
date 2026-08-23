"""Schémas d'entrée du module 16."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class PropertyPredictionInput(BaseModel):
    property_id: Optional[int] = None
    property_type: Optional[str] = None
    city: Optional[str] = None
    postal_code: Optional[str] = None
    living_area: Optional[float] = Field(None, gt=0, le=100_000)
    rooms: Optional[int] = Field(None, ge=0, le=500)
    bedrooms: Optional[int] = Field(None, ge=0, le=500)
    energy_class: Optional[str] = Field(None, pattern="^[A-Ga-g]$")
    equipment: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def property_or_features(self):
        if self.property_id is None and not (self.city and self.living_area and self.property_type):
            raise ValueError("property_id ou (property_type, city et living_area) est requis")
        return self


class RentEstimateRequest(PropertyPredictionInput):
    include_market_observations: bool = True


class VacancyPredictionRequest(BaseModel):
    property_id: int
    horizon_days: int = Field(90, ge=7, le=730)


class PaymentRiskRequest(BaseModel):
    tenant_id: int
    horizon_days: int = Field(90, ge=7, le=365)


class SalePriceRequest(PropertyPredictionInput):
    include_market_observations: bool = True


class FinancialAnomalyRequest(BaseModel):
    bank_account_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    sensitivity: float = Field(3.0, ge=1.5, le=6.0)
    persist: bool = True


class PredictionReview(BaseModel):
    decision: str = Field(..., pattern="^(accepted|rejected|overridden)$")
    notes: Optional[str] = Field(None, max_length=1000)


class ChatSessionCreate(BaseModel):
    locale: str = Field("fr", pattern="^(fr|en|es|de|it)$")
    context: Dict[str, Any] = Field(default_factory=dict)


class ChatMessageCreate(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    context: Dict[str, Any] = Field(default_factory=dict)


class AppointmentCreate(BaseModel):
    property_id: Optional[int] = None
    starts_at: datetime
    duration_minutes: int = Field(30, ge=15, le=240)
    purpose: str = Field(..., min_length=3, max_length=255)
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=2000)


class AssistantTicketCreate(BaseModel):
    property_id: int
    lease_id: Optional[int] = None
    category: str = Field("autre", pattern="^(plomberie|electricite|chauffage|serrurerie|peinture|toiture|parties_communes|menuiserie|autre)$")
    urgency: str = Field("moyen", pattern="^(faible|moyen|eleve|critique)$")
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=3, max_length=10000)
    location: Optional[str] = Field(None, max_length=255)
    confirm: bool = False


class ManagerSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=255)
    entity_types: List[str] = Field(
        default_factory=lambda: ["property", "tenant", "lease", "ticket"]
    )
    limit: int = Field(10, ge=1, le=50)


class QuickActionRequest(BaseModel):
    action: str = Field(..., pattern="^(create_ticket|trigger_workflow|create_appointment)$")
    parameters: Dict[str, Any] = Field(default_factory=dict)
    confirm: bool = False


class WorkflowCreate(BaseModel):
    name: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    event_type: str = Field(..., min_length=3, max_length=100)
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(..., min_length=1, max_length=20)
    is_active: bool = True
    priority: int = Field(100, ge=0, le=1000)
    stop_on_error: bool = True


class WorkflowUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=3, max_length=255)
    description: Optional[str] = None
    event_type: Optional[str] = Field(None, min_length=3, max_length=100)
    conditions: Optional[List[Dict[str, Any]]] = None
    actions: Optional[List[Dict[str, Any]]] = Field(None, min_length=1, max_length=20)
    is_active: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=1000)
    stop_on_error: Optional[bool] = None


class AutomationEvent(BaseModel):
    event_type: str = Field(..., min_length=3, max_length=100)
    payload: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str = Field(..., min_length=3, max_length=160)
    dry_run: bool = False


class MarketObservationCreate(BaseModel):
    source: str = Field(..., min_length=2, max_length=100)
    external_reference: Optional[str] = None
    competitor: Optional[str] = None
    listing_type: str = Field(..., pattern="^(rent|sale)$")
    property_type: str
    city: str
    postal_code: Optional[str] = None
    area: float = Field(..., gt=0)
    rooms: Optional[int] = Field(None, ge=0)
    price: float = Field(..., gt=0)
    charges: float = Field(0, ge=0)
    url: Optional[str] = None
    attributes: Dict[str, Any] = Field(default_factory=dict)
    observed_on: date = Field(default_factory=date.today)


class MarketIndexCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=50)
    name: str
    geography: str
    period: str
    value: float
    variation_percent: Optional[float] = None
    source: str
    source_url: Optional[str] = None
    published_on: Optional[date] = None
