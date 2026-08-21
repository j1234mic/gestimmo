"""Schémas de validation du module locataires."""

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.tenant import (
    ApplicationStatus,
    ContractType,
    DocumentType,
    EmploymentStatus,
    GuaranteeScheme,
    GuarantorType,
    IncidentPriority,
    IncidentStatus,
    IncomeType,
    LeaseStatus,
    LegalCaseStatus,
    PaymentStatus,
    SuretyType,
    TenantStatus,
    VerificationStatus,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class GuarantorCreate(BaseModel):
    guarantor_type: GuarantorType = GuarantorType.INDIVIDUAL
    company_name: Optional[str] = Field(None, max_length=255)
    first_name: Optional[str] = Field(None, max_length=100)
    last_name: Optional[str] = Field(None, max_length=100)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: Optional[str] = "Française"
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=30)
    address: Optional[str] = None
    postal_code: Optional[str] = Field(None, max_length=10)
    city: Optional[str] = None
    country: Optional[str] = "France"
    employment_status: Optional[EmploymentStatus] = None
    occupation: Optional[str] = None
    employer_name: Optional[str] = None
    contract_type: Optional[ContractType] = None
    employment_start_date: Optional[date] = None
    monthly_net_income: float = Field(0, ge=0)
    other_monthly_income: float = Field(0, ge=0)
    surety_type: SuretyType = SuretyType.SOLIDARY
    guarantee_scheme: GuaranteeScheme = GuaranteeScheme.PERSONAL
    guarantee_reference: Optional[str] = None
    guaranteed_amount: Optional[float] = Field(None, ge=0)
    guarantee_start_date: Optional[date] = None
    guarantee_end_date: Optional[date] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_identity(self):
        if self.guarantor_type == GuarantorType.COMPANY and not self.company_name:
            raise ValueError("company_name est requis pour un garant personne morale")
        if self.guarantor_type == GuarantorType.INDIVIDUAL and not (self.first_name and self.last_name):
            raise ValueError("first_name et last_name sont requis pour un garant personne physique")
        return self


class GuarantorUpdate(BaseModel):
    company_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    birth_date: Optional[date] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    employment_status: Optional[EmploymentStatus] = None
    occupation: Optional[str] = None
    employer_name: Optional[str] = None
    contract_type: Optional[ContractType] = None
    employment_start_date: Optional[date] = None
    monthly_net_income: Optional[float] = Field(None, ge=0)
    other_monthly_income: Optional[float] = Field(None, ge=0)
    surety_type: Optional[SuretyType] = None
    guarantee_scheme: Optional[GuaranteeScheme] = None
    guarantee_reference: Optional[str] = None
    guaranteed_amount: Optional[float] = Field(None, ge=0)
    guarantee_start_date: Optional[date] = None
    guarantee_end_date: Optional[date] = None
    is_verified: Optional[bool] = None
    notes: Optional[str] = None


class ApplicationCreate(BaseModel):
    property_id: Optional[int] = None
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: str = "Française"
    email: EmailStr
    phone: str = Field(..., min_length=6, max_length=30)
    address: Optional[str] = None
    postal_code: Optional[str] = Field(None, max_length=10)
    city: Optional[str] = None
    country: str = "France"
    employment_status: EmploymentStatus
    occupation: Optional[str] = None
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    contract_type: Optional[ContractType] = None
    employment_start_date: Optional[date] = None
    trial_period_end: Optional[date] = None
    monthly_net_income: float = Field(..., ge=0)
    other_monthly_income: float = Field(0, ge=0)
    current_monthly_rent: Optional[float] = Field(None, ge=0)
    desired_move_in_date: Optional[date] = None
    occupants_count: int = Field(1, ge=1, le=30)
    notes: Optional[str] = Field(None, max_length=5000)
    privacy_consent: bool
    guarantors: List[GuarantorCreate] = Field(default_factory=list, max_length=5)

    @field_validator("privacy_consent")
    @classmethod
    def consent_is_required(cls, value: bool):
        if not value:
            raise ValueError("Le consentement au traitement du dossier est requis")
        return value


class ApplicationStatusUpdate(BaseModel):
    status: ApplicationStatus
    reason: Optional[str] = Field(None, max_length=5000)
    force: bool = False

    @model_validator(mode="after")
    def refusal_requires_reason(self):
        if self.status == ApplicationStatus.REFUSED and not self.reason:
            raise ValueError("Un motif est requis pour refuser une candidature")
        return self


class DocumentReview(BaseModel):
    verification_status: VerificationStatus
    reason: Optional[str] = None


class TenantIncomeCreate(BaseModel):
    income_type: IncomeType
    label: Optional[str] = None
    monthly_amount: float = Field(..., gt=0)
    payer: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    is_verified: bool = False


class EmergencyContactCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    relationship: Optional[str] = None
    phone: str = Field(..., min_length=6, max_length=30)
    email: Optional[EmailStr] = None
    is_primary: bool = False


class RentalHistoryCreate(BaseModel):
    address: str = Field(..., min_length=3)
    city: Optional[str] = None
    landlord_name: Optional[str] = None
    landlord_phone: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_rent: Optional[float] = Field(None, ge=0)
    departure_reason: Optional[str] = None
    payment_incidents: bool = False
    reference_checked: bool = False

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date doit être postérieure à start_date")
        return self


class TenantCreate(BaseModel):
    status: TenantStatus = TenantStatus.ACTIVE
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: str = "Française"
    email: EmailStr
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "France"
    employment_status: Optional[EmploymentStatus] = None
    occupation: Optional[str] = None
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    contract_type: Optional[ContractType] = None
    employment_start_date: Optional[date] = None
    trial_period_end: Optional[date] = None
    monthly_net_income: float = Field(0, ge=0)
    other_monthly_income: float = Field(0, ge=0)
    notes: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    incomes: List[TenantIncomeCreate] = Field(default_factory=list)
    emergency_contacts: List[EmergencyContactCreate] = Field(default_factory=list)
    rental_history: List[RentalHistoryCreate] = Field(default_factory=list)
    guarantors: List[GuarantorCreate] = Field(default_factory=list)


class TenantUpdate(BaseModel):
    status: Optional[TenantStatus] = None
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    employment_status: Optional[EmploymentStatus] = None
    occupation: Optional[str] = None
    employer_name: Optional[str] = None
    employer_address: Optional[str] = None
    contract_type: Optional[ContractType] = None
    employment_start_date: Optional[date] = None
    trial_period_end: Optional[date] = None
    monthly_net_income: Optional[float] = Field(None, ge=0)
    other_monthly_income: Optional[float] = Field(None, ge=0)
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class LeaseCreate(BaseModel):
    property_id: int
    status: LeaseStatus = LeaseStatus.DRAFT
    start_date: date
    end_date: Optional[date] = None
    monthly_rent: float = Field(..., gt=0)
    monthly_charges: float = Field(0, ge=0)
    deposit: float = Field(0, ge=0)
    payment_day: int = Field(5, ge=1, le=28)
    lease_type: str = "unfurnished"
    signed_at: Optional[datetime] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date doit être postérieure à start_date")
        return self


class LeaseUpdate(BaseModel):
    status: Optional[LeaseStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    monthly_rent: Optional[float] = Field(None, gt=0)
    monthly_charges: Optional[float] = Field(None, ge=0)
    deposit: Optional[float] = Field(None, ge=0)
    payment_day: Optional[int] = Field(None, ge=1, le=28)
    lease_type: Optional[str] = None
    signed_at: Optional[datetime] = None
    notes: Optional[str] = None


class PaymentCreate(BaseModel):
    lease_id: int
    period: str = Field(..., pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    due_date: date
    amount_due: float = Field(..., gt=0)
    notes: Optional[str] = None


class PaymentUpdate(BaseModel):
    amount_paid: float = Field(..., ge=0)
    paid_at: Optional[datetime] = None
    payment_method: Optional[str] = None
    external_reference: Optional[str] = None
    notes: Optional[str] = None


class IncidentCreate(BaseModel):
    lease_id: Optional[int] = None
    category: str = Field(..., min_length=2, max_length=100)
    title: str = Field(..., min_length=2, max_length=255)
    description: str = Field(..., min_length=3, max_length=10000)
    priority: IncidentPriority = IncidentPriority.NORMAL
    attachment_url: Optional[str] = None


class IncidentUpdate(BaseModel):
    status: Optional[IncidentStatus] = None
    priority: Optional[IncidentPriority] = None
    assigned_to: Optional[str] = None
    resolution: Optional[str] = None


class TenantMessageCreate(BaseModel):
    subject: Optional[str] = Field(None, max_length=255)
    content: str = Field(..., min_length=1, max_length=20000)
    attachment_url: Optional[str] = None


class InteractionCreate(BaseModel):
    interaction_type: str = Field(..., min_length=2, max_length=50)
    direction: str = Field("internal", pattern="^(incoming|outgoing|internal)$")
    subject: Optional[str] = None
    content: str = Field(..., min_length=1)
    related_entity_type: Optional[str] = None
    related_entity_id: Optional[int] = None


class LegalCaseCreate(BaseModel):
    lease_id: Optional[int] = None
    status: LegalCaseStatus = LegalCaseStatus.OPEN
    case_type: str = Field(..., min_length=2, max_length=100)
    opened_at: date
    outstanding_amount: float = Field(0, ge=0)
    court_reference: Optional[str] = None
    lawyer_name: Optional[str] = None
    next_action_date: Optional[date] = None
    description: Optional[str] = None


class LegalCaseUpdate(BaseModel):
    status: Optional[LegalCaseStatus] = None
    closed_at: Optional[date] = None
    outstanding_amount: Optional[float] = Field(None, ge=0)
    court_reference: Optional[str] = None
    lawyer_name: Optional[str] = None
    next_action_date: Optional[date] = None
    description: Optional[str] = None
    resolution: Optional[str] = None


class PortalLogin(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class PortalActivation(BaseModel):
    application_reference: str
    tracking_token: str = Field(..., min_length=20)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str):
        if not any(c.isupper() for c in value) or not any(c.islower() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("Le mot de passe doit contenir une majuscule, une minuscule et un chiffre")
        return value


class PortalRefresh(BaseModel):
    refresh_token: str


class PortalAccessUpdate(BaseModel):
    enabled: bool = True
    temporary_password: Optional[str] = Field(None, min_length=8, max_length=128)


class ApplicationResponse(ORMModel):
    id: int
    reference: str
    property_id: Optional[int]
    tenant_id: Optional[int]
    status: ApplicationStatus
    first_name: str
    last_name: str
    email: EmailStr
    phone: str
    employment_status: EmploymentStatus
    monthly_net_income: float
    other_monthly_income: float
    solvency_score: float
    score_breakdown: dict = Field(default_factory=dict)
    risk_level: str
    submitted_at: Optional[datetime]


class TenantResponse(ORMModel):
    id: int
    reference: str
    status: TenantStatus
    first_name: str
    last_name: str
    email: EmailStr
    phone: Optional[str]
    city: Optional[str]
    solvency_score: float
    reliability_score: float
    portal_enabled: bool
    is_active: bool
    created_at: Optional[datetime]


class DocumentResponse(ORMModel):
    id: int
    document_type: DocumentType
    pay_slip_period: Optional[str]
    original_filename: str
    url: str
    file_size: Optional[int]
    verification_status: VerificationStatus
    ocr_confidence: float
    verification_checks: dict = Field(default_factory=dict)
    uploaded_at: Optional[datetime]


class LeaseResponse(ORMModel):
    id: int
    reference: str
    tenant_id: int
    property_id: int
    status: LeaseStatus
    start_date: date
    end_date: Optional[date]
    monthly_rent: float
    monthly_charges: float
    payment_day: int
    document_url: Optional[str]


class PaymentResponse(ORMModel):
    id: int
    reference: str
    tenant_id: int
    lease_id: int
    period: str
    due_date: date
    amount_due: float
    amount_paid: float
    status: PaymentStatus
    paid_at: Optional[datetime]
    payment_method: Optional[str]
