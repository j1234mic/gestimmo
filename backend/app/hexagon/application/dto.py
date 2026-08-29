"""DTO (Data Transfer Objects) de la couche application.

Objets simples transmis aux cas d'usage. Ils découlent des schémas API
mais sont découplés de FastAPI/Pydantic pour rester testables sans HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import List, Optional


class PropertyTypeDTO(str, Enum):
    APARTMENT = "apartment"
    HOUSE = "house"
    STUDIO = "studio"
    VILLA = "villa"
    OFFICE = "office"
    COMMERCIAL = "commercial"
    WAREHOUSE = "warehouse"
    LAND_AGRICULTURAL = "land_agricultural"
    LAND_BUILDABLE = "land_buildable"
    PARKING = "parking"
    GARAGE = "garage"
    BUILDING = "building"


class PropertyStatusDTO(str, Enum):
    AVAILABLE = "available"
    RENTED = "rented"
    FOR_SALE = "for_sale"
    UNDER_RENOVATION = "under_renovation"
    RESERVED = "reserved"
    WITHDRAWN = "withdrawn"


class OwnerTypeDTO(str, Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"
    SCI = "sci"
    JOINT_OWNERSHIP = "joint"


@dataclass
class PropertyCreateDTO:
    type: PropertyTypeDTO
    title: str
    address: str
    postal_code: str
    city: str
    status: Optional[PropertyStatusDTO] = None
    description: Optional[str] = None
    address_complement: Optional[str] = None
    country: str = "France"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    portfolio_id: Optional[int] = None
    living_area: Optional[float] = None
    total_area: Optional[float] = None
    land_area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    toilets: Optional[int] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    construction_year: Optional[int] = None
    renovation_year: Optional[int] = None
    rent_price: Optional[float] = None
    charges: Optional[float] = None
    deposit: Optional[float] = None
    sale_price: Optional[float] = None
    property_tax: Optional[float] = None
    tags: List[str] = field(default_factory=list)
    equipment: dict = field(default_factory=dict)


@dataclass
class PropertyUpdateDTO:
    type: Optional[PropertyTypeDTO] = None
    title: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    status: Optional[PropertyStatusDTO] = None
    description: Optional[str] = None
    rent_price: Optional[float] = None
    sale_price: Optional[float] = None
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    portfolio_id: Optional[int] = None
    # (champs supplémentaires volontairement non exhaustifs : l'usage réel
    #  étend via **extra sans casser la logique existante)


@dataclass
class PropertyFilterDTO:
    search: Optional[str] = None
    type: Optional[list] = None
    status: Optional[list] = None
    city: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_area: Optional[float] = None
    max_area: Optional[float] = None
    min_rooms: Optional[int] = None
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    portfolio_id: Optional[int] = None
    allowed_scopes: Optional[list] = None
    allowed_entity_ids: Optional[list] = None
    allowed_agency_ids: Optional[list] = None
    allowed_portfolio_ids: Optional[list] = None


@dataclass
class OwnerCreateDTO:
    owner_type: OwnerTypeDTO = OwnerTypeDTO.INDIVIDUAL
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    country: str = "France"
    tax_regime: Optional[str] = None
    siret: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = field(default_factory=list)


@dataclass
class OwnerUpdateDTO:
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    company_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    tax_regime: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None
