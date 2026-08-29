# backend/app/schemas/owner.py

from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import date, datetime
from app.models.owner import OwnerType, TaxRegime, MandateType


# ============================================
# OWNER
# ============================================
class OwnerCreate(BaseModel):
    owner_type: OwnerType = OwnerType.INDIVIDUAL
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: Optional[str] = "Française"
    
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = "France"
    
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_holder: Optional[str] = None
    
    tax_regime: Optional[TaxRegime] = None
    siret: Optional[str] = None
    vat_number: Optional[str] = None
    tax_id: Optional[str] = None
    
    notes: Optional[str] = None
    tags: List[str] = []


class OwnerUpdate(BaseModel):
    owner_type: Optional[OwnerType] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    birth_date: Optional[date] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    tax_regime: Optional[TaxRegime] = None
    siret: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


class OwnerResponse(BaseModel):
    id: int
    secure_id: Optional[str] = None
    reference: str
    owner_type: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    tax_regime: Optional[str] = None
    is_active: bool = True
    properties_count: int = 0
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class OwnerDetailResponse(OwnerResponse):
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_holder: Optional[str] = None
    siret: Optional[str] = None
    vat_number: Optional[str] = None
    tax_id: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []
    properties: List[dict] = []
    mandates: List[dict] = []


# ============================================
# MANDATE
# ============================================
class MandateCreate(BaseModel):
    mandate_type: MandateType
    property_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    renewal_automatic: bool = False
    fees_percentage: Optional[float] = None
    fees_fixed: Optional[float] = None
    minimum_fees: Optional[float] = None
    notes: Optional[str] = None


class MandateResponse(BaseModel):
    id: int
    reference: str
    mandate_type: str
    owner_id: int
    property_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    status: str
    fees_percentage: Optional[float] = None
    fees_fixed: Optional[float] = None
    
    class Config:
        from_attributes = True


class MandateSignatureRequest(BaseModel):
    typed_signature: str = Field(..., min_length=1, max_length=255)
    signature_image_base64: Optional[str] = None
    consent: Optional[str] = "Je reconnais avoir lu le mandat et consens à le signer électroniquement."


# ============================================
# PROPERTY-OWNER LINK
# ============================================
class PropertyOwnerLink(BaseModel):
    property_id: int
    ownership_percentage: float = 100.0
    is_main_owner: bool = True
    acquisition_date: Optional[date] = None
    acquisition_price: Optional[float] = None