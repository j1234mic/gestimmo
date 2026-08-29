"""Schémas des modules complémentaires de gestion immobilière (18 à 31)."""
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.extension import (
    AcquisitionStatus,
    BookingStatus,
    DevelopmentProgramStatus,
    FiscalDeclarationStatus,
    LegalFileStatus,
    LegalCaseType,
    LoanStatus,
    LoanType,
    PublicLeadStatus,
    ServiceAgreementStatus,
    ShortTermPlatform,
    TaskPriority,
    TaskStatus,
    UtilityMeterType,
)

_SCHEMA_CONFIG = {"from_attributes": True}


class _Base(BaseModel):
    model_config = _SCHEMA_CONFIG


# ---------------------------------------------------------------------------
# Module 18 — courte durée
# ---------------------------------------------------------------------------
class ShortTermListingCreate(BaseModel):
    property_id: int
    platform: ShortTermPlatform = ShortTermPlatform.DIRECT
    external_id: Optional[str] = None
    name: Optional[str] = None
    nightly_rate: float = 0
    min_nights: int = 1
    max_guests: int = 2
    cleaning_fee: float = 0
    cancellation_policy: Optional[str] = None
    active: bool = True


class ShortTermListingUpdate(BaseModel):
    platform: Optional[ShortTermPlatform] = None
    external_id: Optional[str] = None
    name: Optional[str] = None
    nightly_rate: Optional[float] = None
    min_nights: Optional[int] = None
    max_guests: Optional[int] = None
    cleaning_fee: Optional[float] = None
    cancellation_policy: Optional[str] = None
    active: Optional[bool] = None


class ShortTermBookingCreate(BaseModel):
    listing_id: int
    check_in: date
    check_out: date
    guest_name: str
    guest_email: Optional[str] = None
    guests: int = 1
    amount: float = 0
    cleaning_fee: float = 0
    tax_amount: float = 0
    status: BookingStatus = BookingStatus.PENDING
    source: Optional[str] = None
    external_reservation_id: Optional[str] = None
    notes: Optional[str] = None


class ShortTermBookingUpdate(BaseModel):
    check_in: Optional[date] = None
    check_out: Optional[date] = None
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    guests: Optional[int] = None
    amount: Optional[float] = None
    cleaning_fee: Optional[float] = None
    tax_amount: Optional[float] = None
    status: Optional[BookingStatus] = None
    source: Optional[str] = None
    external_reservation_id: Optional[str] = None
    notes: Optional[str] = None


class ShortTermPriceRuleCreate(BaseModel):
    listing_id: int
    label: Optional[str] = None
    date_from: date
    date_to: date
    rate_multiplier: float = 1.0
    weekend_multiplier: float = 1.0
    min_nights: Optional[int] = None
    active: bool = True


class ShortTermListingResponse(_Base):
    id: int
    property_id: int
    platform: str
    external_id: Optional[str] = None
    name: Optional[str] = None
    nightly_rate: float
    min_nights: int
    max_guests: int
    cleaning_fee: float
    cancellation_policy: Optional[str] = None
    active: bool
    created_at: Optional[datetime] = None


class ShortTermBookingResponse(_Base):
    id: int
    listing_id: int
    check_in: date
    check_out: date
    guest_name: str
    guest_email: Optional[str] = None
    guests: int
    amount: float
    cleaning_fee: float
    tax_amount: float
    status: str
    source: Optional[str] = None
    external_reservation_id: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ShortTermPriceRuleResponse(_Base):
    id: int
    listing_id: int
    label: Optional[str] = None
    date_from: date
    date_to: date
    rate_multiplier: float
    weekend_multiplier: float
    min_nights: Optional[int] = None
    active: bool


# ---------------------------------------------------------------------------
# Module 19 — contentieux
# ---------------------------------------------------------------------------
class LegalCaseCreate(BaseModel):
    case_type: LegalCaseType = LegalCaseType.OTHER
    status: LegalFileStatus = LegalFileStatus.OPEN
    subject: str
    property_id: Optional[int] = None
    owner_id: Optional[int] = None
    tenant_id: Optional[int] = None
    provider_id: Optional[int] = None
    amount_in_dispute: float = 0
    court: Optional[str] = None
    case_number: Optional[str] = None
    opened_at: Optional[date] = None
    notes: Optional[str] = None


class LegalCaseUpdate(BaseModel):
    case_type: Optional[LegalCaseType] = None
    status: Optional[LegalFileStatus] = None
    subject: Optional[str] = None
    amount_in_dispute: Optional[float] = None
    court: Optional[str] = None
    case_number: Optional[str] = None
    closed_at: Optional[date] = None
    notes: Optional[str] = None


class LegalActionCreate(BaseModel):
    case_id: int
    action_type: str
    action_date: date
    description: Optional[str] = None
    outcome: Optional[str] = None
    notes: Optional[str] = None


class LegalCaseResponse(_Base):
    id: int
    reference: str
    case_type: str
    status: str
    subject: str
    property_id: Optional[int] = None
    owner_id: Optional[int] = None
    tenant_id: Optional[int] = None
    provider_id: Optional[int] = None
    amount_in_dispute: float
    court: Optional[str] = None
    case_number: Optional[str] = None
    opened_at: Optional[date] = None
    closed_at: Optional[date] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class LegalActionResponse(_Base):
    id: int
    case_id: int
    action_type: str
    action_date: date
    description: Optional[str] = None
    outcome: Optional[str] = None
    created_by: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Module 20 — fiscalité
# ---------------------------------------------------------------------------
class FiscalYearRecordCreate(BaseModel):
    owner_id: int
    property_id: Optional[int] = None
    fiscal_year: int
    regime: Optional[str] = None
    rental_income: float = 0
    deductible_charges: float = 0
    amortization: float = 0
    notes: Optional[str] = None


class FiscalYearRecordUpdate(BaseModel):
    regime: Optional[str] = None
    rental_income: Optional[float] = None
    deductible_charges: Optional[float] = None
    amortization: Optional[float] = None
    status: Optional[FiscalDeclarationStatus] = None
    submitted_at: Optional[date] = None
    notes: Optional[str] = None


class FiscalYearRecordResponse(_Base):
    id: int
    owner_id: int
    property_id: Optional[int] = None
    fiscal_year: int
    regime: Optional[str] = None
    rental_income: float
    deductible_charges: float
    amortization: float
    result: float
    tax_amount: float
    status: str
    generated_pdf_url: Optional[str] = None
    submitted_at: Optional[date] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Module 21 — financement
# ---------------------------------------------------------------------------
class PropertyLoanCreate(BaseModel):
    owner_id: int
    property_id: Optional[int] = None
    lender: str
    loan_type: LoanType = LoanType.CLASSIC
    principal: float
    interest_rate: float
    duration_months: int
    start_date: date
    insurance_monthly: float = 0
    notes: Optional[str] = None


class PropertyLoanUpdate(BaseModel):
    lender: Optional[str] = None
    loan_type: Optional[LoanType] = None
    principal: Optional[float] = None
    interest_rate: Optional[float] = None
    duration_months: Optional[int] = None
    status: Optional[LoanStatus] = None
    insurance_monthly: Optional[float] = None
    notes: Optional[str] = None


class LoanPaymentUpdate(BaseModel):
    status: str
    paid_at: Optional[datetime] = None


class PropertyLoanResponse(_Base):
    id: int
    owner_id: int
    property_id: Optional[int] = None
    lender: str
    loan_type: str
    principal: float
    interest_rate: float
    duration_months: int
    start_date: date
    monthly_payment: float
    insurance_monthly: float
    status: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class LoanPaymentResponse(_Base):
    id: int
    loan_id: int
    payment_number: int
    due_date: date
    principal_part: float
    interest_part: float
    total_part: float
    insurance_part: float
    status: str
    paid_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Module 22 — portail public / site vitrine
# ---------------------------------------------------------------------------
class PublicPageCreate(BaseModel):
    title: str
    slug: str
    content: str = ""
    status: str = "draft"
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    published_at: Optional[datetime] = None


class PublicPageUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    content: Optional[str] = None
    status: Optional[str] = None
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    published_at: Optional[datetime] = None


class PublicAgentCreate(BaseModel):
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    photo_url: Optional[str] = None
    bio: Optional[str] = None
    order: int = 0
    active: bool = True


class PublicAgentUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    photo_url: Optional[str] = None
    bio: Optional[str] = None
    order: Optional[int] = None
    active: Optional[bool] = None


class PublicTestimonialCreate(BaseModel):
    client_name: str
    client_role: Optional[str] = None
    content: str
    rating: int = Field(5, ge=1, le=5)
    property_id: Optional[int] = None
    published: bool = True


class PublicTestimonialUpdate(BaseModel):
    client_name: Optional[str] = None
    client_role: Optional[str] = None
    content: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    property_id: Optional[int] = None
    published: Optional[bool] = None


class PublicNewsPostCreate(BaseModel):
    title: str
    slug: str
    excerpt: Optional[str] = None
    content: str = ""
    author: Optional[str] = None
    cover_url: Optional[str] = None
    status: str = "draft"
    published_at: Optional[datetime] = None


class PublicNewsPostUpdate(BaseModel):
    title: Optional[str] = None
    slug: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None
    author: Optional[str] = None
    cover_url: Optional[str] = None
    status: Optional[str] = None
    published_at: Optional[datetime] = None


class PublicLeadCreate(BaseModel):
    request_type: str = "contact"
    name: str
    email: str
    phone: Optional[str] = None
    property_id: Optional[int] = None
    message: Optional[str] = None
    preferred_date: Optional[date] = None


class PublicLeadUpdate(BaseModel):
    status: Optional[PublicLeadStatus] = None
    message: Optional[str] = None


class PublicPageResponse(_Base):
    id: int
    title: str
    slug: str
    content: str
    status: str
    seo_title: Optional[str] = None
    seo_description: Optional[str] = None
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PublicAgentResponse(_Base):
    id: int
    name: str
    role: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    photo_url: Optional[str] = None
    bio: Optional[str] = None
    order: int
    active: bool
    created_at: Optional[datetime] = None


class PublicTestimonialResponse(_Base):
    id: int
    client_name: str
    client_role: Optional[str] = None
    content: str
    rating: int
    property_id: Optional[int] = None
    published: bool
    created_at: Optional[datetime] = None


class PublicNewsPostResponse(_Base):
    id: int
    title: str
    slug: str
    excerpt: Optional[str] = None
    content: str
    author: Optional[str] = None
    cover_url: Optional[str] = None
    status: str
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class PublicLeadResponse(_Base):
    id: int
    reference: str
    request_type: str
    name: str
    email: str
    phone: Optional[str] = None
    property_id: Optional[int] = None
    message: Optional[str] = None
    status: str
    preferred_date: Optional[date] = None
    created_at: Optional[datetime] = None


class PublicLeadPublicResponse(_Base):
    reference: str
    request_type: str
    status: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Services résidentiels
# ---------------------------------------------------------------------------
class ServiceAgreementCreate(BaseModel):
    property_id: int
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    service_type: str
    contract_label: Optional[str] = None
    monthly_amount: float = 0
    billing_type: str = "monthly"
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    notes: Optional[str] = None


class ServiceAgreementUpdate(BaseModel):
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    service_type: Optional[str] = None
    contract_label: Optional[str] = None
    monthly_amount: Optional[float] = None
    billing_type: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: Optional[ServiceAgreementStatus] = None
    notes: Optional[str] = None


class ServiceInvoiceCreate(BaseModel):
    agreement_id: int
    period: str
    amount: float = 0
    vat_amount: float = 0
    due_date: Optional[date] = None
    notes: Optional[str] = None


class ServiceInvoiceUpdate(BaseModel):
    amount: Optional[float] = None
    vat_amount: Optional[float] = None
    status: Optional[str] = None
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None


class ServiceAgreementResponse(_Base):
    id: int
    property_id: int
    tenant_id: Optional[int] = None
    owner_id: Optional[int] = None
    service_type: str
    contract_label: Optional[str] = None
    monthly_amount: float
    billing_type: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class ServiceInvoiceResponse(_Base):
    id: int
    agreement_id: int
    period: str
    amount: float
    vat_amount: float
    total: float
    status: str
    due_date: Optional[date] = None
    paid_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Accès, clés & sûreté
# ---------------------------------------------------------------------------
class AccessKeyCreate(BaseModel):
    property_id: int
    label: str
    key_type: str = "cle"
    serial: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class AccessKeyUpdate(BaseModel):
    label: Optional[str] = None
    key_type: Optional[str] = None
    serial: Optional[str] = None
    location: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class KeyOperationCreate(BaseModel):
    key_id: int
    action: str
    borrowed_by: Optional[str] = None
    occurred_at: Optional[datetime] = None
    notes: Optional[str] = None


class AccessKeyResponse(_Base):
    id: int
    property_id: int
    label: str
    key_type: str
    serial: Optional[str] = None
    location: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class KeyOperationResponse(_Base):
    id: int
    key_id: int
    action: str
    borrowed_by: Optional[str] = None
    occurred_at: Optional[datetime] = None
    returned_at: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Compteurs & consommation énergie
# ---------------------------------------------------------------------------
class UtilityMeterCreate(BaseModel):
    property_id: int
    meter_type: UtilityMeterType = UtilityMeterType.OTHER
    serial: Optional[str] = None
    unit: str = "kWh"
    location: Optional[str] = None
    initial_reading: float = 0


class UtilityMeterUpdate(BaseModel):
    meter_type: Optional[UtilityMeterType] = None
    serial: Optional[str] = None
    unit: Optional[str] = None
    location: Optional[str] = None
    initial_reading: Optional[float] = None


class UtilityReadingCreate(BaseModel):
    meter_id: int
    reading_date: date
    value: float
    photo_url: Optional[str] = None
    source: str = "manual"
    notes: Optional[str] = None


class UtilityBillCreate(BaseModel):
    property_id: int
    period: str
    utility_type: UtilityMeterType = UtilityMeterType.OTHER
    amount: float = 0
    consumption: float = 0
    unit_price: float = 0
    notes: Optional[str] = None


class UtilityBillUpdate(BaseModel):
    amount: Optional[float] = None
    consumption: Optional[float] = None
    unit_price: Optional[float] = None
    status: Optional[str] = None
    settled_at: Optional[datetime] = None
    notes: Optional[str] = None


class UtilityMeterResponse(_Base):
    id: int
    property_id: int
    meter_type: str
    serial: Optional[str] = None
    unit: str
    location: Optional[str] = None
    initial_reading: float
    created_at: Optional[datetime] = None


class UtilityReadingResponse(_Base):
    id: int
    meter_id: int
    reading_date: date
    value: float
    photo_url: Optional[str] = None
    source: str
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class UtilityBillResponse(_Base):
    id: int
    property_id: int
    period: str
    utility_type: str
    amount: float
    consumption: float
    unit_price: float
    status: str
    settled_at: Optional[datetime] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Développement / VEFA
# ---------------------------------------------------------------------------
class DevelopmentProgramCreate(BaseModel):
    name: str
    program_type: str = "residential"
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    surface: Optional[float] = None
    total_units: int = 0
    expected_delivery: Optional[date] = None
    permit_number: Optional[str] = None
    status: DevelopmentProgramStatus = DevelopmentProgramStatus.PLANNING
    developer: Optional[str] = None
    notes: Optional[str] = None


class DevelopmentProgramUpdate(BaseModel):
    name: Optional[str] = None
    program_type: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    surface: Optional[float] = None
    total_units: Optional[int] = None
    expected_delivery: Optional[date] = None
    permit_number: Optional[str] = None
    status: Optional[DevelopmentProgramStatus] = None
    developer: Optional[str] = None
    notes: Optional[str] = None


class DevelopmentUnitCreate(BaseModel):
    program_id: int
    label: str
    unit_type: str = "apartment"
    surface: Optional[float] = None
    price_ht: Optional[float] = None
    tva_rate: float = 20
    status: str = "available"
    floor: Optional[int] = None
    notes: Optional[str] = None


class DevelopmentUnitUpdate(BaseModel):
    label: Optional[str] = None
    unit_type: Optional[str] = None
    surface: Optional[float] = None
    price_ht: Optional[float] = None
    tva_rate: Optional[float] = None
    status: Optional[str] = None
    floor: Optional[int] = None
    notes: Optional[str] = None


class VefaReservationCreate(BaseModel):
    unit_id: int
    buyer_name: str
    buyer_email: Optional[str] = None
    deposit: float = 0
    reservation_date: date
    notes: Optional[str] = None


class VefaReservationUpdate(BaseModel):
    buyer_name: Optional[str] = None
    buyer_email: Optional[str] = None
    deposit: Optional[float] = None
    status: Optional[str] = None
    signed_at: Optional[datetime] = None
    notes: Optional[str] = None


class DevelopmentProgramResponse(_Base):
    id: int
    reference: str
    name: str
    program_type: str
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    surface: Optional[float] = None
    total_units: int
    expected_delivery: Optional[date] = None
    permit_number: Optional[str] = None
    status: str
    developer: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class DevelopmentUnitResponse(_Base):
    id: int
    program_id: int
    label: str
    unit_type: str
    surface: Optional[float] = None
    price_ht: Optional[float] = None
    tva_rate: float
    price_ttc: Optional[float] = None
    status: str
    floor: Optional[int] = None
    notes: Optional[str] = None


class VefaReservationResponse(_Base):
    id: int
    unit_id: int
    buyer_name: str
    buyer_email: Optional[str] = None
    deposit: float
    reservation_date: date
    status: str
    signed_at: Optional[datetime] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Investisseurs / fonds
# ---------------------------------------------------------------------------
class InvestmentFundCreate(BaseModel):
    name: str
    fund_type: str = "scpi"
    description: Optional[str] = None
    total_capital: float = 0
    nav: float = 0
    nav_date: Optional[date] = None
    status: str = "active"


class InvestmentFundUpdate(BaseModel):
    name: Optional[str] = None
    fund_type: Optional[str] = None
    description: Optional[str] = None
    total_capital: Optional[float] = None
    nav: Optional[float] = None
    nav_date: Optional[date] = None
    status: Optional[str] = None


class FundSubscriptionCreate(BaseModel):
    fund_id: int
    investor_name: str
    investor_email: Optional[str] = None
    amount: float = 0
    units: float = 0
    subscription_date: date
    status: str = "pending"


class FundSubscriptionUpdate(BaseModel):
    investor_name: Optional[str] = None
    investor_email: Optional[str] = None
    amount: Optional[float] = None
    units: Optional[float] = None
    status: Optional[str] = None


class FundDistributionCreate(BaseModel):
    fund_id: int
    period: str
    amount_per_unit: float = 0
    total_amount: float = 0
    payment_date: Optional[date] = None
    status: str = "planned"
    notes: Optional[str] = None


class FundDistributionUpdate(BaseModel):
    amount_per_unit: Optional[float] = None
    total_amount: Optional[float] = None
    payment_date: Optional[date] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class InvestmentFundResponse(_Base):
    id: int
    name: str
    fund_type: str
    description: Optional[str] = None
    total_capital: float
    nav: float
    nav_date: Optional[date] = None
    status: str
    created_at: Optional[datetime] = None


class FundSubscriptionResponse(_Base):
    id: int
    fund_id: int
    investor_name: str
    investor_email: Optional[str] = None
    amount: float
    units: float
    subscription_date: date
    status: str
    created_at: Optional[datetime] = None


class FundDistributionResponse(_Base):
    id: int
    fund_id: int
    period: str
    amount_per_unit: float
    total_amount: float
    payment_date: Optional[date] = None
    status: str
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Performance énergétique & rénovation
# ---------------------------------------------------------------------------
class EnergyAuditCreate(BaseModel):
    property_id: int
    audit_date: date
    energy_class_before: Optional[str] = None
    energy_class_after: Optional[str] = None
    primary_energy: Optional[float] = None
    ghg: Optional[float] = None
    estimated_cost: Optional[float] = None
    advisor: Optional[str] = None
    report_url: Optional[str] = None
    notes: Optional[str] = None


class EnergyAuditUpdate(BaseModel):
    energy_class_before: Optional[str] = None
    energy_class_after: Optional[str] = None
    primary_energy: Optional[float] = None
    ghg: Optional[float] = None
    estimated_cost: Optional[float] = None
    advisor: Optional[str] = None
    report_url: Optional[str] = None
    notes: Optional[str] = None


class EnergyRenovationProjectCreate(BaseModel):
    audit_id: Optional[int] = None
    property_id: int
    title: str
    description: Optional[str] = None
    budget: float = 0
    estimated_savings: float = 0
    status: str = "proposed"
    start_date: Optional[date] = None
    completion_date: Optional[date] = None


class EnergyRenovationProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    budget: Optional[float] = None
    estimated_savings: Optional[float] = None
    status: Optional[str] = None
    start_date: Optional[date] = None
    completion_date: Optional[date] = None


class EnergyGrantCreate(BaseModel):
    project_id: int
    program_name: str
    amount: float = 0
    application_date: Optional[date] = None
    status: str = "pending"
    notes: Optional[str] = None


class EnergyGrantUpdate(BaseModel):
    amount: Optional[float] = None
    status: Optional[str] = None
    granted_at: Optional[date] = None
    notes: Optional[str] = None


class EnergyAuditResponse(_Base):
    id: int
    property_id: int
    audit_date: date
    energy_class_before: Optional[str] = None
    energy_class_after: Optional[str] = None
    primary_energy: Optional[float] = None
    ghg: Optional[float] = None
    estimated_cost: Optional[float] = None
    advisor: Optional[str] = None
    report_url: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class EnergyRenovationProjectResponse(_Base):
    id: int
    audit_id: Optional[int] = None
    property_id: int
    title: str
    description: Optional[str] = None
    budget: float
    estimated_savings: float
    status: str
    start_date: Optional[date] = None
    completion_date: Optional[date] = None
    created_at: Optional[datetime] = None


class EnergyGrantResponse(_Base):
    id: int
    project_id: int
    program_name: str
    amount: float
    application_date: Optional[date] = None
    status: str
    granted_at: Optional[date] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Qualité de service
# ---------------------------------------------------------------------------
class SatisfactionSurveyCreate(BaseModel):
    respondent_type: str
    respondent_id: int
    property_id: Optional[int] = None
    nps_score: Optional[int] = Field(None, ge=0, le=10)
    csat: Optional[int] = Field(None, ge=1, le=5)
    comment: Optional[str] = None
    source: str = "app"


class SatisfactionSurveyResponse(_Base):
    id: int
    respondent_type: str
    respondent_id: int
    property_id: Optional[int] = None
    nps_score: Optional[int] = None
    csat: Optional[int] = None
    comment: Optional[str] = None
    source: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Tâches internes
# ---------------------------------------------------------------------------
class TaskCreate(BaseModel):
    entity_type: str
    entity_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    priority: TaskPriority = TaskPriority.NORMAL
    due_date: Optional[datetime] = None
    related_url: Optional[str] = None


class TaskUpdate(BaseModel):
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    title: Optional[str] = None
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    priority: Optional[TaskPriority] = None
    status: Optional[TaskStatus] = None
    due_date: Optional[datetime] = None
    related_url: Optional[str] = None


class TaskCommentCreate(BaseModel):
    author: Optional[str] = None
    body: str


class TaskResponse(_Base):
    id: int
    entity_type: str
    entity_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    assignee_id: Optional[int] = None
    priority: str
    status: str
    due_date: Optional[datetime] = None
    related_url: Optional[str] = None
    created_by: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class TaskCommentResponse(_Base):
    id: int
    task_id: int
    author: Optional[str] = None
    body: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Sourcing & acquisitions
# ---------------------------------------------------------------------------
class AcquisitionOpportunityCreate(BaseModel):
    source: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    cadastre: Optional[str] = None
    expected_price: Optional[float] = None
    market_price: Optional[float] = None
    potential_rent: Optional[float] = None
    total_area: Optional[float] = None
    condition: Optional[str] = None
    status: AcquisitionStatus = AcquisitionStatus.PROSPECTING
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None


class AcquisitionOpportunityUpdate(BaseModel):
    source: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    cadastre: Optional[str] = None
    expected_price: Optional[float] = None
    market_price: Optional[float] = None
    potential_rent: Optional[float] = None
    total_area: Optional[float] = None
    condition: Optional[str] = None
    status: Optional[AcquisitionStatus] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None


class DueDiligenceItemCreate(BaseModel):
    opportunity_id: int
    label: str
    category: Optional[str] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None


class DueDiligenceItemUpdate(BaseModel):
    label: Optional[str] = None
    category: Optional[str] = None
    status: Optional[str] = None
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None


class AcquisitionOpportunityResponse(_Base):
    id: int
    reference: str
    source: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    cadastre: Optional[str] = None
    expected_price: Optional[float] = None
    market_price: Optional[float] = None
    potential_rent: Optional[float] = None
    total_area: Optional[float] = None
    condition: Optional[str] = None
    status: str
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None


class DueDiligenceItemResponse(_Base):
    id: int
    opportunity_id: int
    label: str
    category: Optional[str] = None
    status: str
    due_date: Optional[date] = None
    completed_at: Optional[datetime] = None
    notes: Optional[str] = None


class UsageSummary(BaseModel):
    total: int
    data: list[Any] = Field(default_factory=list)
