"""Entité métier Property (agrégat Bien immobilier).

Entité pure, sans dépendance ORM. Les adaptateurs SQLAlchemy effectuent
la conversion depuis/vers les modèles persistants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


class PropertyType(str, Enum):
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


class PropertyStatus(str, Enum):
    AVAILABLE = "available"
    RENTED = "rented"
    FOR_SALE = "for_sale"
    UNDER_RENOVATION = "under_renovation"
    RESERVED = "reserved"
    WITHDRAWN = "withdrawn"


class HeatingType(str, Enum):
    ELECTRIC = "electric"
    GAS = "gas"
    OIL = "oil"
    HEAT_PUMP = "heat_pump"
    WOOD = "wood"
    COLLECTIVE = "collective"
    SOLAR = "solar"


class EnergyClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"


@dataclass
class Property:
    """Agrégat Bien immobilier (représentation canonique du domaine)."""

    reference: str
    type: PropertyType
    title: str
    address: str
    postal_code: str
    city: str

    id: Optional[int] = None
    secure_id: Optional[str] = None

    status: PropertyStatus = PropertyStatus.AVAILABLE
    description: Optional[str] = None
    address_complement: Optional[str] = None
    country: str = "France"
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Cloisonnement multi-sociétés / agences (module 12)
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    portfolio_id: Optional[int] = None

    # Caractéristiques physiques
    living_area: Optional[float] = None
    total_area: Optional[float] = None
    land_area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    toilets: Optional[int] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None

    # Construction
    construction_year: Optional[int] = None
    renovation_year: Optional[int] = None
    heating_type: Optional[HeatingType] = None
    energy_class: Optional[EnergyClass] = None
    ges_class: Optional[EnergyClass] = None

    equipment: dict = field(default_factory=dict)
    rent_price: Optional[float] = None
    charges: Optional[float] = None
    deposit: Optional[float] = None
    sale_price: Optional[float] = None
    property_tax: Optional[float] = None

    tags: list = field(default_factory=list)
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def is_publicly_visible(self) -> bool:
        """Règle métier : un bien non authentifié n'est visible que s'il est disponible."""
        return self.is_active and self.status == PropertyStatus.AVAILABLE

    def soft_delete(self) -> None:
        """Suppression logique : le bien reste en base mais n'est plus actif."""
        self.is_active = False
        self.status = PropertyStatus.WITHDRAWN


@dataclass
class PropertyFilter:
    """Critères de recherche d'un bien (paramètre du port de repository)."""

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
class PropertyListItem:
    """Vue liste d'un bien (photo principale ajoutée par l'adaptateur)."""

    id: Optional[int]
    secure_id: Optional[str]
    reference: str
    type: str
    status: str
    title: str
    city: str
    postal_code: str
    rent_price: Optional[float] = None
    sale_price: Optional[float] = None
    living_area: Optional[float] = None
    rooms: Optional[int] = None
    main_photo: Optional[str] = None
    tags: Optional[list] = None
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    portfolio_id: Optional[int] = None


@dataclass
class PropertyStatistics:
    total_properties: int
    by_type: dict
    by_status: dict
    properties_for_sale: int
