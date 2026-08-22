"""Schémas Pydantic du module 8 : CRM et gestion commerciale."""

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.crm import (
    ConditionType,
    InterestLevel,
    ListingStatus,
    Portal,
    ProspectSource,
    ProspectType,
)


# ---------------------------------------------------------------------------
# Prospects
# ---------------------------------------------------------------------------
class ProspectCreate(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    prospect_type: ProspectType = ProspectType.TENANT
    source: ProspectSource = ProspectSource.WEBSITE
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    search_criteria: Dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Critères de recherche : property_types, cities, postal_codes, "
            "min_surface, max_surface, min_rooms, min_bedrooms, equipment, …"
        ),
    )
    assigned_agent: Optional[str] = None
    notes: Optional[str] = None


class ProspectUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    prospect_type: Optional[ProspectType] = None
    source: Optional[ProspectSource] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    search_criteria: Optional[Dict[str, Any]] = None
    assigned_agent: Optional[str] = None
    notes: Optional[str] = None
    last_contact_at: Optional[datetime] = None


class ProspectAdminUpdate(BaseModel):
    status: Optional[str] = None  # actif | converti | dormant | perdu
    lost_reason: Optional[str] = None


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class PipelineStageCreate(BaseModel):
    name: str
    display_order: int = 0
    probability: float = Field(0, ge=0, le=1)
    color: Optional[str] = None
    is_won: bool = False
    is_lost: bool = False


class PipelineStageUpdate(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None
    probability: Optional[float] = Field(None, ge=0, le=1)
    color: Optional[str] = None
    is_won: Optional[bool] = None
    is_lost: Optional[bool] = None
    is_active: Optional[bool] = None


class DealCreate(BaseModel):
    title: str
    prospect_id: int
    property_id: Optional[int] = None
    deal_type: str = "location"
    estimated_value: float = 0
    expected_commission: float = 0
    probability: Optional[float] = Field(None, ge=0, le=1)
    expected_close_date: Optional[date] = None
    assigned_agent: Optional[str] = None
    notes: Optional[str] = None


class DealUpdate(BaseModel):
    title: Optional[str] = None
    property_id: Optional[int] = None
    deal_type: Optional[str] = None
    estimated_value: Optional[float] = None
    expected_commission: Optional[float] = None
    probability: Optional[float] = Field(None, ge=0, le=1)
    expected_close_date: Optional[date] = None
    assigned_agent: Optional[str] = None
    notes: Optional[str] = None


class DealStageChange(BaseModel):
    stage_id: int
    comment: Optional[str] = None
    lost_reason: Optional[str] = None
    changed_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Visites
# ---------------------------------------------------------------------------
class AvailabilitySlot(BaseModel):
    start: str
    end: str


class AvailabilityDayCreate(BaseModel):
    available_date: date
    slots: List[AvailabilitySlot]


class VisitCreate(BaseModel):
    property_id: int
    prospect_id: int
    deal_id: Optional[int] = None
    scheduled_date: date
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    auto_confirm: bool = True
    assigned_agent: Optional[str] = None
    availability_id: Optional[int] = None
    notes: Optional[str] = None


class VisitUpdate(BaseModel):
    scheduled_date: Optional[date] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    assigned_agent: Optional[str] = None
    notes: Optional[str] = None


class VisitCancel(BaseModel):
    reason: Optional[str] = None


class VisitReportCreate(BaseModel):
    overall_rating: Optional[int] = Field(None, ge=1, le=5)
    interest_level: Optional[InterestLevel] = None
    strengths: Optional[str] = None
    weaknesses: Optional[str] = None
    comments: Optional[str] = None
    next_step: Optional[str] = None
    follow_up_date: Optional[date] = None


class VisitorFeedbackCreate(BaseModel):
    visitor_rating: Optional[int] = Field(None, ge=1, le=5)
    visitor_comments: Optional[str] = None
    visitor_would_apply: Optional[bool] = None


class ReminderRequest(BaseModel):
    channels: List[str] = ["email", "sms"]


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------
class MatchingScanRequest(BaseModel):
    prospect_id: Optional[int] = None
    min_score: int = Field(60, ge=0, le=100)
    notify: bool = Field(True, description="Notifie automatiquement l'agent référent")


class MatchNotificationRequest(BaseModel):
    also_email_prospect: bool = False


# ---------------------------------------------------------------------------
# Annonces / portails
# ---------------------------------------------------------------------------
class ListingTemplateCreate(BaseModel):
    name: str
    property_type: Optional[str] = None
    language: str = "fr"
    title_template: Optional[str] = None
    description_template: Optional[str] = None
    is_active: bool = True


class ListingCreate(BaseModel):
    property_id: int
    title: str
    description: Optional[str] = None
    price: Optional[float] = None
    listing_type: str = "location"
    template_id: Optional[int] = None


class ListingUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    listing_type: Optional[str] = None
    status: Optional[ListingStatus] = None


class ListingPublishRequest(BaseModel):
    portals: List[Portal]
    external_references: Optional[Dict[str, str]] = None  # portail → réf. externe


class ListingStatsEntry(BaseModel):
    stat_date: date
    views: int = 0
    contacts: int = 0
    favorites: int = 0
    leads: int = 0
    portal: Optional[Portal] = None


class ListingStatsUpload(BaseModel):
    entries: List[ListingStatsEntry]


# ---------------------------------------------------------------------------
# Transactions (vente)
# ---------------------------------------------------------------------------
class PurchaseOfferCreate(BaseModel):
    property_id: int
    prospect_id: Optional[int] = None
    deal_id: Optional[int] = None
    amount: float
    offer_date: date
    validity_date: Optional[date] = None
    financing_ok: bool = True
    conditions: List[Dict[str, Any]] = Field(default_factory=list)


class OfferDecision(BaseModel):
    note: Optional[str] = None
    create_transaction: bool = Field(
        False, description="Créer le dossier de vente après acceptation"
    )


class SaleTransactionCreate(BaseModel):
    property_id: int
    offer_id: Optional[int] = None
    prospect_id: Optional[int] = None
    deal_id: Optional[int] = None
    buyer_name: Optional[str] = None
    seller_owner_id: Optional[int] = None
    sale_price: float
    commission_rate: float = 0
    commission_fixed: float = 0
    vat_rate: float = 20
    notes: Optional[str] = None


class CompromisSign(BaseModel):
    compromis_date: Optional[date] = None
    notary_name: Optional[str] = None
    notary_email: Optional[str] = None
    notary_phone: Optional[str] = None


class NotaryUpdate(BaseModel):
    notary_name: Optional[str] = None
    notary_email: Optional[str] = None
    notary_phone: Optional[str] = None


class SuspensiveConditionCreate(BaseModel):
    label: str
    condition_type: ConditionType = ConditionType.OTHER
    deadline: Optional[date] = None
    notes: Optional[str] = None


class ConditionDecision(BaseModel):
    decision: str = Field(..., pattern="^(satisfaite|levee|echouee)$")
    notes: Optional[str] = None


class ActeSign(BaseModel):
    acte_signed_at: date
    effective_sale_date: Optional[date] = None
    commission_rate: Optional[float] = None
    commission_fixed: Optional[float] = None


class TransactionEventCreate(BaseModel):
    event_type: str = "notaire"
    label: str
    event_date: Optional[date] = None
    notes: Optional[str] = None
