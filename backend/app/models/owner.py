# backend/app/models/owner.py

from sqlalchemy import (
    Column, Integer, String, Float, Text, Boolean,
    DateTime, Enum, ForeignKey, JSON, Date
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum
from app.database import Base


class OwnerType(str, enum.Enum):
    INDIVIDUAL = "individual"      # Personne physique
    COMPANY = "company"            # Personne morale
    SCI = "sci"                    # SCI
    JOINT_OWNERSHIP = "joint"     # Indivision


class TaxRegime(str, enum.Enum):
    MICRO_FONCIER = "micro_foncier"
    REEL = "reel"
    SCI_IR = "sci_ir"
    SCI_IS = "sci_is"
    BIC = "bic"


class MandateType(str, enum.Enum):
    RENTAL_MANAGEMENT = "rental_management"  # Gestion locative
    SALE = "sale"                             # Mandat de vente
    SEARCH = "search"                         # Recherche de bien


class Owner(Base):
    __tablename__ = "owners"

    id = Column(Integer, primary_key=True, index=True)
    # Identifiant public chiffré (architecture hexagonale). Nullable pour la
    # compatibilité ascendante (backfill effectué dans app.database.init_db).
    secure_id = Column(String(255), unique=True, index=True, nullable=True)
    reference = Column(String(20), unique=True, index=True, nullable=False)

    # Type de propriétaire
    owner_type = Column(Enum(OwnerType), default=OwnerType.INDIVIDUAL)

    # Informations personnelles
    first_name = Column(String(100))
    last_name = Column(String(100))
    company_name = Column(String(200))  # Si personne morale
    birth_date = Column(Date)
    birth_place = Column(String(200))
    nationality = Column(String(100), default="Française")

    # Coordonnées
    email = Column(String(255))
    phone = Column(String(30))
    mobile = Column(String(30))
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="France")

    # Informations bancaires
    bank_name = Column(String(200))
    iban = Column(String(34))
    bic = Column(String(11))
    account_holder = Column(String(200))

    # Informations fiscales
    tax_regime = Column(Enum(TaxRegime))
    siret = Column(String(14))
    vat_number = Column(String(20))
    tax_id = Column(String(50))

    # Documents
    id_document_url = Column(String(500))     # Pièce d'identité
    tax_notice_url = Column(String(500))       # Avis d'imposition
    bank_rib_url = Column(String(500))         # RIB

    # Notes
    notes = Column(Text)
    tags = Column(JSON, default=list)

    # Métadonnées
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    properties = relationship("app.models.property.Property", secondary="property_owners", back_populates="owners")
    mandates = relationship("Mandate", back_populates="owner", cascade="all, delete-orphan")


# Table d'association propriétaires ↔ biens
class PropertyOwner(Base):
    __tablename__ = "property_owners"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"))
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"))
    ownership_percentage = Column(Float, default=100.0)  # % de détention
    is_main_owner = Column(Boolean, default=True)
    acquisition_date = Column(Date)
    acquisition_price = Column(Float)


class Mandate(Base):
    __tablename__ = "mandates"

    id = Column(Integer, primary_key=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="CASCADE"))
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True)

    mandate_type = Column(Enum(MandateType), nullable=False)
    reference = Column(String(50), unique=True)

    # Dates
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    renewal_automatic = Column(Boolean, default=False)
    notice_period_days = Column(Integer, default=90)  # Préavis

    # Conditions financières
    fees_percentage = Column(Float)  # % d'honoraires
    fees_fixed = Column(Float)       # Honoraires fixes
    minimum_fees = Column(Float)     # Honoraires minimum

    # Statut
    status = Column(String(20), default="active")  # active, expired, terminated
    signed_date = Column(Date)
    document_url = Column(String(500))  # Mandat signé

    # Dossier de preuve de signature électronique (aligné sur le module 4)
    signature_hash = Column(String(64))            # SHA-256 de la preuve signée
    signature_document_hash = Column(String(64))   # SHA-256 du mandat signé
    signature_evidence_path = Column(String(700))  # PDF de preuve
    signature_image_path = Column(String(700))     # Signature manuscrite scannée
    signature_consent_at = Column(DateTime(timezone=True))
    signature_ip = Column(String(64))
    signature_user_agent = Column(String(1000))
    signature_provider = Column(String(50), default="internal_simple_signature")
    signature_requested_at = Column(DateTime(timezone=True))

    # Notes
    notes = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relations
    owner = relationship("Owner", back_populates="mandates")
    property = relationship("app.models.property.Property", backref="mandates")