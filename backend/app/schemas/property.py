from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import date, datetime
from app.models.property import PropertyType, PropertyStatus, EnergyClass

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

class PropertyCreate(BaseModel):
    type: PropertyType
    title: str = Field(..., min_length=3, max_length=255)
    description: Optional[str] = None
    status: PropertyStatus = PropertyStatus.AVAILABLE
    
    address: str
    address_complement: Optional[str] = None
    postal_code: str
    city: str
    country: str = "France"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    living_area: Optional[float] = None
    total_area: Optional[float] = None
    land_area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    toilets: Optional[int] = None
    floor: Optional[int] = None
    total_floors: Optional[int] = None
    
    construction_year: Optional[int] = Field(None, ge=1800, le=2030)
    renovation_year: Optional[int] = Field(None, ge=1800, le=2030)
    heating_type: Optional[str] = None
    energy_class: Optional[EnergyClass] = None
    ges_class: Optional[EnergyClass] = None
    
    equipment: EquipmentSchema = Field(default_factory=EquipmentSchema)
    
    rent_price: Optional[float] = None
    charges: Optional[float] = None
    deposit: Optional[float] = None
    sale_price: Optional[float] = None
    property_tax: Optional[float] = None
    
    tags: List[str] = Field(default_factory=list)

class PropertyUpdate(BaseModel):
    type: Optional[PropertyType] = None
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[PropertyStatus] = None
    address: Optional[str] = None
    postal_code: Optional[str] = None
    city: Optional[str] = None
    living_area: Optional[float] = None
    rooms: Optional[int] = None
    bedrooms: Optional[int] = None
    rent_price: Optional[float] = None
    sale_price: Optional[float] = None
    tags: Optional[List[str]] = None

class PropertyResponse(BaseModel):
    id: int
    reference: str
    type: str
    status: str
    title: str
    description: Optional[str]
    address: str
    city: str
    postal_code: str
    living_area: Optional[float]
    rooms: Optional[int]
    bedrooms: Optional[int]
    rent_price: Optional[float]
    sale_price: Optional[float]
    created_at: datetime
    
    class Config:
        from_attributes = True

class PropertyDetailResponse(PropertyResponse):
    photos: List[dict] = []
    documents: List[dict] = []
    evaluations: List[dict] = []
    history: List[dict] = []
