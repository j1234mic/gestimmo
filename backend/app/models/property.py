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
    LAND = "land"
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
    
    type = Column(Enum(PropertyType), nullable=False, default=PropertyType.APARTMENT)
    status = Column(Enum(PropertyStatus), default=PropertyStatus.AVAILABLE)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    
    # Adresse
    address = Column(String(500), nullable=False)
    address_complement = Column(String(255))
    postal_code = Column(String(10), nullable=False)
    city = Column(String(100), nullable=False)
    country = Column(String(100), default="France")
    latitude = Column(Float)
    longitude = Column(Float)
    
    # Caractéristiques
    living_area = Column(Float)
    total_area = Column(Float)
    land_area = Column(Float)
    rooms = Column(Integer)
    bedrooms = Column(Integer)
    bathrooms = Column(Integer)
    toilets = Column(Integer)
    floor = Column(Integer)
    total_floors = Column(Integer)
    
    # Construction
    construction_year = Column(Integer)
    renovation_year = Column(Integer)
    heating_type = Column(String(50))
    energy_class = Column(Enum(EnergyClass))
    ges_class = Column(Enum(EnergyClass))
    
    # Équipements
    equipment = Column(JSON, default=dict)
    
    # Finances
    rent_price = Column(Float)
    charges = Column(Float)
    deposit = Column(Float)
    sale_price = Column(Float)
    property_tax = Column(Float)
    
    # Tags
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

class PropertyPhoto(Base):
    __tablename__ = "property_photos"
    
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    url = Column(String(500), nullable=False)
    filename = Column(String(255))
    is_main = Column(Boolean, default=False)
    virtual_tour_url = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    property = relationship("Property", back_populates="photos")

class PropertyDocument(Base):
    __tablename__ = "property_documents"
    
    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    type = Column(String(50))
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
    event_type = Column(String(50))
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
    source = Column(String(100))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    property = relationship("Property", back_populates="evaluations")
