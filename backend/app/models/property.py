# backend/app/models/property.py

from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean,
    DateTime, Enum, ForeignKey, JSON, Date
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class PropertyType(str, enum.Enum):
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

class PropertyStatus(str, enum.Enum):
    AVAILABLE = "available"
    RENTED = "rented"
    FOR_SALE = "for_sale"
    UNDER_RENOVATION = "under_renovation"
    RESERVED = "reserved"
    WITHDRAWN = "withdrawn"

class HeatingType(str, enum.Enum):
    ELECTRIC = "electric"
    GAS = "gas"
    OIL = "oil"
    HEAT_PUMP = "heat_pump"
    WOOD = "wood"
    COLLECTIVE = "collective"
    SOLAR = "solar"

class EnergyClass(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    F = "F"
    G = "G"

class Property(Base):
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(20), unique=True, index=True, nullable=False)
    
    # Informations générales
    type = Column(Enum(PropertyType), nullable=False)
    status = Column(Enum(PropertyStatus), default=PropertyStatus.AVAILABLE)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Adresse et localisation
    address = Column(String(500), nullable=False)
    address_complement = Column(String(255))
    postal_code = Column(String(10), nullable=False)
    city = Column(String(100), nullable=False)
    country = Column(String(100), default="France")
    latitude = Column(Float)
    longitude = Column(Float)

    # Cloisonnement multi-sociétés / multi-agences (module 12). Ces clés sont
    # volontairement sans FK afin de conserver l'import de données historiques.
    entity_id = Column(Integer, index=True)
    agency_id = Column(Integer, index=True)
    portfolio_id = Column(Integer, index=True)
    
    # Caractéristiques physiques
    living_area = Column(Float)  # Surface habitable en m²
    total_area = Column(Float)   # Surface totale
    land_area = Column(Float)    # Surface terrain
    rooms = Column(Integer)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    toilets = Column(Integer)
    floor = Column(Integer)      # Étage
    total_floors = Column(Integer)
    
    # Construction
    construction_year = Column(Integer)
    renovation_year = Column(Integer)
    heating_type = Column(Enum(HeatingType))
    energy_class = Column(Enum(EnergyClass))
    ges_class = Column(Enum(EnergyClass))  # Gaz à effet de serre
    
    # Équipements
    equipment = Column(JSON, default=dict)
    # Exemple: {
    #   "elevator": True,
    #   "parking": True,
    #   "cellar": True,
    #   "balcony": True,
    #   "terrace": True,
    #   "garden": True,
    #   "swimming_pool": False,
    #   "air_conditioning": True,
    #   "alarm": True,
    #   "intercom": True,
    #   "fiber_optic": True,
    #   "disabled_access": True,
    #   "caretaker": False,
    #   "bike_storage": True,
    #   "laundry_room": True
    # }
    
    # Informations financières
    rent_price = Column(Float)  # Loyer mensuel
    charges = Column(Float)     # Charges mensuelles
    deposit = Column(Float)     # Dépôt de garantie
    sale_price = Column(Float)  # Prix de vente
    property_tax = Column(Float)  # Taxe foncière annuelle
    
    # Tags et catégories
    tags = Column(JSON, default=list)
    
    # Métadonnées
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relations
    photos = relationship("PropertyPhoto", back_populates="property", cascade="all, delete-orphan")
    documents = relationship("PropertyDocument", back_populates="property", cascade="all, delete-orphan")
    history = relationship("PropertyHistory", back_populates="property", cascade="all, delete-orphan")
    evaluations = relationship("PropertyEvaluation", back_populates="property", cascade="all, delete-orphan")
    owners = relationship("Owner", secondary="property_owners", back_populates="properties")


class PropertyPhoto(Base):
    __tablename__ = "property_photos"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    url = Column(String(500), nullable=False)
    filename = Column(String(255))
    is_main = Column(Boolean, default=False)
    is_360 = Column(Boolean, default=False)
    virtual_tour_url = Column(String(500))
    order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    property = relationship("Property", back_populates="photos")

class PropertyDocument(Base):
    __tablename__ = "property_documents"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    type = Column(String(50))  # title_deed, blueprint, technical_diagnosis, etc.
    title = Column(String(255))
    url = Column(String(500))
    filename = Column(String(255))
    file_size = Column(Integer)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
    
    property = relationship("Property", back_populates="documents")

class PropertyHistory(Base):
    __tablename__ = "property_history"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    event_type = Column(String(50))  # tenant_change, rent_change, renovation, evaluation
    description = Column(Text)
    details = Column(JSON)
    date = Column(Date, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    property = relationship("Property", back_populates="history")

class PropertyEvaluation(Base):
    __tablename__ = "property_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    value = Column(Float, nullable=False)
    evaluation_date = Column(Date, nullable=False)
    source = Column(String(100))  # manual, algorithm, api
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    property = relationship("Property", back_populates="evaluations")

