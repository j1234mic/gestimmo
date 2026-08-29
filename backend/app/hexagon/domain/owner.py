"""Entité métier Owner (agrégat Propriétaire).

Entité pure, sans dépendance ORM.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class OwnerType(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"
    SCI = "sci"
    JOINT_OWNERSHIP = "joint"


class TaxRegime(str, Enum):
    MICRO_FONCIER = "micro_foncier"
    REEL = "reel"
    SCI_IR = "sci_ir"
    SCI_IS = "sci_is"
    BIC = "bic"


@dataclass
class Owner:
    """Agrégat Propriétaire (représentation canonique du domaine)."""

    reference: str
    id: Optional[int] = None
    secure_id: Optional[str] = None

    owner_type: OwnerType = OwnerType.INDIVIDUAL

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    birth_date: Optional[date] = None
    birth_place: Optional[str] = None
    nationality: str = "Française"

    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "France"

    bank_name: Optional[str] = None
    iban: Optional[str] = None
    bic: Optional[str] = None
    account_holder: Optional[str] = None

    tax_regime: Optional[TaxRegime] = None
    siret: Optional[str] = None
    vat_number: Optional[str] = None
    tax_id: Optional[str] = None

    notes: Optional[str] = None
    tags: list = field(default_factory=list)

    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    properties_count: int = 0

    @property
    def display_name(self) -> str:
        if self.owner_type == OwnerType.COMPANY and self.company_name:
            return self.company_name
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or self.reference

    def soft_delete(self) -> None:
        self.is_active = False


@dataclass
class OwnerListItem:
    id: Optional[int]
    secure_id: Optional[str]
    reference: str
    owner_type: str
    display_name: str
    email: Optional[str] = None
    city: Optional[str] = None
    is_active: bool = True
    properties_count: int = 0
