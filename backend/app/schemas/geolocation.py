"""Schémas API du module 13."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


POI_CATEGORIES = {"transport", "school", "shop", "hospital", "park"}
TRAVEL_MODES = {"driving", "walking", "cycling", "transit"}


class Coordinate(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class PropertyGeocodeUpdate(Coordinate):
    source: str = "manual"


class POICreate(Coordinate):
    external_id: Optional[str] = None
    provider: str = "manual"
    name: str = Field(min_length=1, max_length=255)
    category: str
    subcategory: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    entity_id: Optional[int] = None

    @field_validator("category")
    @classmethod
    def category_allowed(cls, value):
        if value not in POI_CATEGORIES:
            raise ValueError("Catégorie de point d'intérêt inconnue")
        return value


class ZoneCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    code: Optional[str] = None
    description: Optional[str] = None
    color: str = Field("#1f6feb", pattern=r"^#[0-9a-fA-F]{6}$")
    polygon: Dict[str, Any]
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None

    @field_validator("polygon")
    @classmethod
    def valid_geojson_polygon(cls, value):
        if value.get("type") != "Polygon":
            raise ValueError("Un GeoJSON Polygon est requis")
        coordinates = value.get("coordinates")
        if not coordinates or not coordinates[0] or len(coordinates[0]) < 4:
            raise ValueError("Le polygone doit contenir au moins quatre positions")
        ring = coordinates[0]
        if ring[0] != ring[-1]:
            raise ValueError("L'anneau GeoJSON doit être fermé")
        for position in ring:
            if len(position) < 2 or not (-180 <= position[0] <= 180) or not (-90 <= position[1] <= 90):
                raise ValueError("Coordonnée GeoJSON invalide")
        return value


class ZoneUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9a-fA-F]{6}$")
    polygon: Optional[Dict[str, Any]] = None
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None
    is_active: Optional[bool] = None

    @field_validator("polygon")
    @classmethod
    def valid_geojson_polygon(cls, value):
        if value is None:
            return value
        return ZoneCreate(
            name="validation", polygon=value
        ).polygon


class AgentAssignment(BaseModel):
    user_id: int
    is_primary: bool = False


class TravelTimeRequest(BaseModel):
    destination: Coordinate
    travel_mode: str = "driving"
    average_speed_kmh: Optional[float] = Field(None, gt=0, le=150)

    @field_validator("travel_mode")
    @classmethod
    def mode_allowed(cls, value):
        if value not in TRAVEL_MODES:
            raise ValueError("Mode de déplacement inconnu")
        return value


class VisitCreate(BaseModel):
    property_id: int
    agent_user_id: Optional[int] = None
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    starts_at: datetime
    duration_minutes: int = Field(30, ge=5, le=480)
    notes: Optional[str] = None
    entity_id: Optional[int] = None
    agency_id: Optional[int] = None


class VisitUpdate(BaseModel):
    agent_user_id: Optional[int] = None
    visitor_name: Optional[str] = None
    visitor_phone: Optional[str] = None
    starts_at: Optional[datetime] = None
    duration_minutes: Optional[int] = Field(None, ge=5, le=480)
    status: Optional[str] = None
    notes: Optional[str] = None


class RouteOptimizeRequest(BaseModel):
    name: str = "Tournée optimisée"
    visit_ids: List[int] = Field(min_length=1)
    start: Coordinate
    end: Optional[Coordinate] = None
    travel_mode: str = "driving"
    return_to_start: bool = False
    route_date: Optional[str] = None
    agent_user_id: Optional[int] = None

    @field_validator("travel_mode")
    @classmethod
    def mode_allowed(cls, value):
        if value not in TRAVEL_MODES:
            raise ValueError("Mode de déplacement inconnu")
        return value
