"""Schémas de validation du module baux et contrats."""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.models.lease_contract import (
    ChargeMethod,
    InspectionStatus,
    InspectionType,
    ItemCondition,
    LeaseContractType,
    NoticeGivenBy,
    NoticeReason,
    NoticeStatus,
    RenewalMode,
    RentFrequency,
    RentIndexType,
)
from app.models.tenant import LeaseStatus


class CustomClauseInput(BaseModel):
    title: str = Field(..., min_length=2, max_length=255)
    content: str = Field(..., min_length=3, max_length=20_000)
    display_order: int = 0
    is_required: bool = False


class LeaseContractCreate(BaseModel):
    tenant_id: int
    property_id: int
    lease_type: LeaseContractType
    template_id: Optional[int] = None
    status: LeaseStatus = LeaseStatus.DRAFT
    start_date: date
    end_date: Optional[date] = None
    duration_months: Optional[int] = Field(None, ge=1, le=1200)
    tacit_renewal: bool = True
    renewal_notice_months: int = Field(6, ge=1, le=24)
    rent_excluding_charges: float = Field(..., gt=0)
    charges: float = Field(0, ge=0)
    charge_method: ChargeMethod = ChargeMethod.PROVISION
    deposit: float = Field(0, ge=0)
    rent_index_type: RentIndexType = RentIndexType.NONE
    base_index_value: Optional[float] = Field(None, gt=0)
    base_index_date: Optional[date] = None
    next_revision_date: Optional[date] = None
    rent_frequency: RentFrequency = RentFrequency.MONTHLY
    payment_method: str = Field("bank_transfer", max_length=80)
    payment_day: int = Field(5, ge=1, le=28)
    resolutory_clause: bool = True
    resolutory_clause_text: Optional[str] = Field(None, max_length=20_000)
    special_conditions: Optional[str] = Field(None, max_length=30_000)
    custom_variables: dict[str, Any] = Field(default_factory=dict)
    clause_ids: list[int] = Field(default_factory=list)
    custom_clauses: list[CustomClauseInput] = Field(default_factory=list)
    signed_at: Optional[datetime] = None
    notes: Optional[str] = None

    @model_validator(mode="after")
    def validate_dates_and_index(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date doit être postérieure à start_date")
        if self.rent_index_type != RentIndexType.NONE and not self.base_index_value:
            raise ValueError("base_index_value est requis lorsqu'un indice de révision est sélectionné")
        return self


class LeaseContractUpdate(BaseModel):
    status: Optional[LeaseStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    duration_months: Optional[int] = Field(None, ge=1, le=1200)
    tacit_renewal: Optional[bool] = None
    renewal_notice_months: Optional[int] = Field(None, ge=1, le=24)
    rent_excluding_charges: Optional[float] = Field(None, gt=0)
    charges: Optional[float] = Field(None, ge=0)
    charge_method: Optional[ChargeMethod] = None
    deposit: Optional[float] = Field(None, ge=0)
    rent_index_type: Optional[RentIndexType] = None
    base_index_value: Optional[float] = Field(None, gt=0)
    base_index_date: Optional[date] = None
    next_revision_date: Optional[date] = None
    rent_frequency: Optional[RentFrequency] = None
    payment_method: Optional[str] = None
    payment_day: Optional[int] = Field(None, ge=1, le=28)
    resolutory_clause: Optional[bool] = None
    resolutory_clause_text: Optional[str] = None
    special_conditions: Optional[str] = None
    custom_variables: Optional[dict[str, Any]] = None
    notes: Optional[str] = None


class LeaseTemplateCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)
    lease_type: LeaseContractType
    description: Optional[str] = None
    title_template: str = "Contrat de location — ${property_address}"
    introduction_template: Optional[str] = None
    footer_template: Optional[str] = None
    variables_schema: dict[str, Any] = Field(default_factory=dict)
    is_default: bool = False
    clause_ids: list[int] = Field(default_factory=list)


class LeaseClauseCreate(BaseModel):
    code: str = Field(..., min_length=2, max_length=80, pattern=r"^[A-Z0-9_-]+$")
    title: str = Field(..., min_length=2, max_length=255)
    content_template: str = Field(..., min_length=3, max_length=20_000)
    compatible_lease_types: list[LeaseContractType] = Field(default_factory=list)
    category: str = "general"
    is_mandatory: bool = False


class ClauseAssignmentCreate(BaseModel):
    clause_id: Optional[int] = None
    title: Optional[str] = Field(None, min_length=2, max_length=255)
    content: Optional[str] = Field(None, min_length=3, max_length=20_000)
    display_order: int = 0
    is_required: bool = False

    @model_validator(mode="after")
    def custom_clause_requires_content(self):
        if self.clause_id is None and not (self.title and self.content):
            raise ValueError("title et content sont requis pour une clause personnalisée")
        return self


class RentIndexValueCreate(BaseModel):
    index_type: RentIndexType
    period: str = Field(..., min_length=2, max_length=20)
    publication_date: date
    value: float = Field(..., gt=0)
    geography: str = "France"
    source: Optional[str] = None
    source_url: Optional[str] = None

    @field_validator("index_type")
    @classmethod
    def index_cannot_be_none(cls, value):
        if value == RentIndexType.NONE:
            raise ValueError("Un indice réel est requis")
        return value


class RentCapRuleCreate(BaseModel):
    name: str = Field(..., min_length=3)
    lease_type: Optional[LeaseContractType] = None
    geography: str = "France"
    valid_from: date
    valid_to: Optional[date] = None
    maximum_increase_percent: float = Field(..., ge=0, le=100)
    legal_reference: str = Field(..., min_length=3)
    source_url: Optional[str] = None

    @model_validator(mode="after")
    def dates_are_ordered(self):
        if self.valid_to and self.valid_to < self.valid_from:
            raise ValueError("valid_to doit être postérieure à valid_from")
        return self


class RentRevisionCreate(BaseModel):
    effective_date: date
    new_index_value: Optional[float] = Field(None, gt=0)
    index_value_id: Optional[int] = None
    old_index_value: Optional[float] = Field(None, gt=0)
    cap_rule_id: Optional[int] = None
    manual_cap_percent: Optional[float] = Field(None, ge=0, le=100)
    notify_tenant: bool = True

    @model_validator(mode="after")
    def index_value_required(self):
        if self.new_index_value is None and self.index_value_id is None:
            raise ValueError("new_index_value ou index_value_id est requis")
        return self


class RenewalCreate(BaseModel):
    mode: RenewalMode
    planned_date: date
    new_end_date: Optional[date] = None
    new_rent: Optional[float] = Field(None, gt=0)
    notes: Optional[str] = None


class AmendmentCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=255)
    effective_date: date
    reason: Optional[str] = None
    changes: dict[str, Any] = Field(default_factory=dict)
    clauses: list[CustomClauseInput] = Field(default_factory=list)


class NoticeCreate(BaseModel):
    given_by: NoticeGivenBy
    reason: NoticeReason
    reason_details: Optional[str] = None
    notice_date: date
    notice_period_months: Optional[int] = Field(None, ge=0, le=24)
    effective_end_date: Optional[date] = None
    legal_basis: Optional[str] = None
    delivery_method: Optional[str] = None

    @model_validator(mode="after")
    def owner_reason_is_restricted(self):
        if self.given_by == NoticeGivenBy.OWNER and self.reason not in {
            NoticeReason.SALE,
            NoticeReason.REPOSSESSION,
            NoticeReason.LEGITIMATE_REASON,
            NoticeReason.LEASE_EXPIRY,
        }:
            raise ValueError("Le motif de congé propriétaire doit être vente, reprise ou motif légitime")
        return self


class NoticeStatusUpdate(BaseModel):
    status: NoticeStatus


class SignaturePartyCreate(BaseModel):
    party_type: str = Field(..., pattern="^(tenant|owner|guarantor|other)$")
    party_id: Optional[int] = None
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    signing_order: int = Field(1, ge=1, le=20)


class SignatureEnvelopeCreate(BaseModel):
    document_id: int
    subject: str = Field(..., min_length=3, max_length=255)
    message: Optional[str] = None
    expires_at: Optional[datetime] = None
    parties: list[SignaturePartyCreate] = Field(..., min_length=1, max_length=20)


class PublicSignatureInput(BaseModel):
    typed_signature: str = Field(..., min_length=2, max_length=255)
    consent: bool
    signature_image_base64: Optional[str] = None

    @field_validator("consent")
    @classmethod
    def explicit_consent_required(cls, value):
        if not value:
            raise ValueError("Le consentement explicite est requis")
        return value


class SignatureDeclineInput(BaseModel):
    reason: str = Field(..., min_length=3, max_length=5000)


class InspectionCreate(BaseModel):
    inspection_type: InspectionType
    inspection_date: datetime
    conducted_by: Optional[str] = None
    general_comments: Optional[str] = None
    comparison_inspection_id: Optional[int] = None
    client_uuid: Optional[str] = Field(None, pattern=r"^[0-9a-fA-F-]{36}$")


class InspectionUpdate(BaseModel):
    status: Optional[InspectionStatus] = None
    inspection_date: Optional[datetime] = None
    conducted_by: Optional[str] = None
    general_comments: Optional[str] = None


class InspectionItemInput(BaseModel):
    client_uuid: Optional[str] = None
    category: str = Field(..., pattern="^(floor|wall|ceiling|equipment|opening|heating|other)$")
    name: str = Field(..., min_length=1, max_length=255)
    condition: ItemCondition
    cleanliness: Optional[str] = None
    description: Optional[str] = None
    estimated_repair_cost: float = Field(0, ge=0)
    depreciation_percent: float = Field(0, ge=0, le=100)
    tenant_responsibility_percent: float = Field(100, ge=0, le=100)


class InspectionRoomCreate(BaseModel):
    client_uuid: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=150)
    room_type: Optional[str] = None
    display_order: int = 0
    comments: Optional[str] = None
    items: list[InspectionItemInput] = Field(default_factory=list)


class InspectionMeterCreate(BaseModel):
    meter_type: str = Field(..., pattern="^(water|gas|electricity|other)$")
    serial_number: Optional[str] = None
    reading: str = Field(..., min_length=1, max_length=100)
    unit: Optional[str] = None
    location: Optional[str] = None


class InspectionKeyCreate(BaseModel):
    key_type: str = Field(..., min_length=1, max_length=100)
    quantity: int = Field(..., ge=0, le=100)
    comments: Optional[str] = None


class InspectionBulkSync(BaseModel):
    client_uuid: str
    sync_version: int = Field(..., ge=1)
    inspection_date: datetime
    general_comments: Optional[str] = None
    rooms: list[InspectionRoomCreate] = Field(default_factory=list)
    meters: list[InspectionMeterCreate] = Field(default_factory=list)
    keys: list[InspectionKeyCreate] = Field(default_factory=list)


class DeductionApproval(BaseModel):
    deduction_id: int
    approved_amount: float = Field(..., ge=0)
    approval_notes: Optional[str] = None


class InspectionDeductionsApproval(BaseModel):
    deductions: list[DeductionApproval]


class InspectionSignatureCreate(BaseModel):
    signer_type: str = Field(..., pattern="^(tenant|owner|manager|agent)$")
    signer_name: str = Field(..., min_length=2, max_length=255)
    signer_email: Optional[EmailStr] = None
    signature_image_base64: str
    consent: bool

    @field_validator("consent")
    @classmethod
    def consent_required(cls, value):
        if not value:
            raise ValueError("Le consentement explicite est requis")
        return value


class DocumentArchiveInput(BaseModel):
    retention_until: Optional[date] = None
    legal_hold: bool = False


class ContractEventInput(BaseModel):
    title: str
    description: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)
