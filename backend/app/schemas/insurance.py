"""Schémas du module assurances / sinistres."""
from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.models.insurance import ClaimType, ClaimStatus, InsuranceType


class InsuranceContractCreate(BaseModel):
    property_id: int
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    insurance_type: InsuranceType
    policy_number: str
    company: str
    broker: Optional[str] = None
    expiry_date: date
    premium: float = 0
    document_id: Optional[int] = None
    notes: Optional[str] = None


class InsuranceContractUpdate(BaseModel):
    insurance_type: Optional[InsuranceType] = None
    policy_number: Optional[str] = None
    company: Optional[str] = None
    broker: Optional[str] = None
    expiry_date: Optional[date] = None
    premium: Optional[float] = None
    document_id: Optional[int] = None
    notes: Optional[str] = None


class InsuranceContractResponse(BaseModel):
    id: int
    property_id: int
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    insurance_type: str
    policy_number: str
    company: str
    broker: Optional[str] = None
    expiry_date: date
    premium: float = 0
    document_id: Optional[int] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AttestationCreate(BaseModel):
    property_id: int
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    tenant_id: Optional[int] = None


class AttestationUpdate(BaseModel):
    status: Optional[str] = None
    valid_until: Optional[date] = None
    document_url: Optional[str] = None
    tenant_id: Optional[int] = None


class AttestationResponse(BaseModel):
    id: int
    property_id: int
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    tenant_id: Optional[int] = None
    status: str
    valid_until: Optional[date] = None
    document_url: Optional[str] = None
    requested_at: Optional[datetime] = None
    reminder_count: int = 0
    last_reminded_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ClaimCreate(BaseModel):
    property_id: int
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    claim_type: ClaimType
    incident_date: date
    circumstances: Optional[str] = None
    involved_people: list[Any] = Field(default_factory=list)
    evidence: list[Any] = Field(default_factory=list)


class ClaimUpdate(BaseModel):
    status: Optional[ClaimStatus] = None
    claim_type: Optional[ClaimType] = None
    incident_date: Optional[date] = None
    circumstances: Optional[str] = None
    insurance_case_number: Optional[str] = None
    expert: Optional[str] = None
    key_dates: Optional[dict] = None
    involved_people: Optional[list[Any]] = None
    evidence: Optional[list[Any]] = None
    proposed_indemnity: Optional[float] = None
    received_indemnity: Optional[float] = None
    restoration_work: Optional[str] = None


class ClaimResponse(BaseModel):
    id: int
    property_id: int
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    claim_type: str
    status: str
    incident_date: date
    circumstances: Optional[str] = None
    insurance_case_number: Optional[str] = None
    expert: Optional[str] = None
    key_dates: Optional[dict] = None
    involved_people: list[Any] = Field(default_factory=list)
    evidence: list[Any] = Field(default_factory=list)
    proposed_indemnity: Optional[float] = None
    received_indemnity: Optional[float] = None
    restoration_work: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True
