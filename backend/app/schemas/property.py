# backend/app/schemas/property.py

from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List, Dict
from datetime import date, datetime
from app.models.property import (
    PropertyType, PropertyStatus, HeatingType, EnergyClass
)

class EquipmentSchema(BaseModel):
    elevator: bool = False
    parking: bool = False
    cellar: bool = False
    balcony: bool = False
    terrace: bool = False
    garden: bool = False
    swimming_pool: bool = False
    air_conditioning: bool = False
    alarm: bool = False
    intercom: bool = False
    fiber_optic: bool = False
    disabled_access: bool = False
    caretaker: bool = False
    bike_storage: bool = False
    laundry_room: bool = False

class PropertyCreate(BaseModel):
    type: PropertyType
    status: PropertyStatus = PropertyStatus.AVAILABLE
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    
    # Adresse
    address: str
    address_complement: Optional[str] = None
    postal_code: str
    city: str
    country: str = "France"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    # Caractéristiques
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
    construction_year: Optional[int] = Field(None, ge=1800, le=2030)
    renovation_year: Optional[int] = Field(None, ge=1800, le=2030)
    heating_type: Optional[HeatingType] = None
    energy_class: Optional[EnergyClass] = None
    ges_class: Optional[EnergyClass] = None
    
    # Équipements
    equipment: EquipmentSchema = Field(default_factory=EquipmentSchema)
    
    # Finances
    rent_price: Optional[float] = None
    charges: Optional[float] = None
    deposit: Optional[float] = None
    sale_price: Optional[float] = None
    property_tax: Optional[float] = None
    
    # Tags
    tags: List[str] = Field(default_factory=list)

class PropertyUpdate(PropertyCreate):
    type: Optional[PropertyType] = None
    title: Optional[str] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    status: Optional[PropertyStatus] = None

class PropertyResponse(BaseModel):
    id: int
    reference: str
    type: str
    status: str
    title: str
    description: Optional[str] = None
    address: str
    city: str
    postal_code: str
    living_area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    rent_price: Optional[float] = None
    sale_price: Optional[float] = None
    main_photo: Optional[str] = None
    tags: Optional[List[str]] = None          # ✅ AJOUTÉ
    equipment: Optional[dict] = None           # ✅ AJOUTÉ
    bathrooms: Optional[int] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    construction_year: Optional[int] = None
    energy_class: Optional[str] = None
    heating_type: Optional[str] = None
    total_area: Optional[float] = None
    land_area: Optional[float] = None
    created_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True

class PhotoResponse(BaseModel):
    id: int
    url: str
    is_main: bool
    is_360: bool
    virtual_tour_url: Optional[str]
    
    class Config:
        from_attributes = True

class DocumentResponse(BaseModel):
    id: int
    type: str
    title: str
    url: str
    filename: str
    file_size: Optional[int]
    uploaded_at: datetime
    
    class Config:
        from_attributes = True

class EvaluationResponse(BaseModel):
    id: int
    value: float
    evaluation_date: date
    source: str
    notes: Optional[str]
    
    class Config:
        from_attributes = True

class HistoryResponse(BaseModel):
    id: int
    event_type: str
    description: str
    date: date
    details: Optional[dict]
    
    class Config:
        from_attributes = True

class PropertyDetailResponse(PropertyResponse):
    photos: List[PhotoResponse]
    documents: List[DocumentResponse]
    evaluations: List[EvaluationResponse]
    history: List[HistoryResponse]

class PropertyFilter(BaseModel):
    search: Optional[str] = None
    type: Optional[List[PropertyType]] = None
    status: Optional[List[PropertyStatus]] = None
    city: Optional[str] = None
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    min_area: Optional[float] = None
    max_area: Optional[float] = None
    min_rooms: Optional[int] = None
    tags: Optional[List[str]] = None
    available_from: Optional[date] = None