"""Modèles du module 6 : maintenance et travaux.

Le module couvre le ticketing des demandes d'intervention, le workflow de
traitement avec SLA et escalade, l'annuaire des prestataires, la maintenance
préventive, la gestion des travaux lourds, le suivi financier et l'inventaire
des équipements.
"""

import enum

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


# ---------------------------------------------------------------------------
# Enums métier
# ---------------------------------------------------------------------------
class TicketSource(str, enum.Enum):
    TENANT = "tenant"                  # Portail/app locataire
    MANAGER = "manager"                # Gestionnaire
    OWNER = "owner"                    # Propriétaire
    AUTOMATIC = "automatic"            # Maintenance préventive
    OTHER = "other"


class TicketCategory(str, enum.Enum):
    PLOMBERIE = "plomberie"
    ELECTRICITE = "electricite"
    CHAUFFAGE = "chauffage"            # Chauffage / climatisation
    SERRURERIE = "serrurerie"
    PEINTURE = "peinture"
    TOITURE = "toiture"
    PARTIES_COMMUNES = "parties_communes"
    MENUISERIE = "menuiserie"
    AUTRE = "autre"


class TicketUrgency(str, enum.Enum):
    LOW = "faible"
    MEDIUM = "moyen"
    HIGH = "eleve"
    CRITICAL = "critique"


class TicketStatus(str, enum.Enum):
    NEW = "nouveau"
    AWAITING_OWNER = "en_attente_validation_proprietaire"
    VALIDATED = "valide"
    PROVIDER_ASSIGNED = "prestataire_assigne"
    QUOTE_PENDING = "devis_en_attente"
    QUOTE_VALIDATED = "devis_valide"
    PLANNED = "intervention_planifiee"
    IN_PROGRESS = "en_cours"
    COMPLETED = "termine"
    QUALITY_CONTROL = "controle_qualite"
    CLOSED = "cloture"
    CANCELLED = "annule"


class QuoteStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"


class MaintenanceType(str, enum.Enum):
    RAMONAGE = "ramonage"
    BOILER = "chaudiere"
    SMOKE_DETECTOR = "detecteurs_fumee"
    GREEN_SPACES = "espaces_verts"
    COMMON_CLEANING = "nettoyage_parties_communes"
    ELEVATOR = "ascenseur"
    CUSTOM = "personnalisable"


class MaintenancePlanStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class WorkProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    VALIDATED = "valide"
    IN_PROGRESS = "en_cours"
    COMPLETED = "termine"
    RECEIVED = "recu"                  # Réception des travaux
    CANCELLED = "annule"


class WorkDocumentType(str, enum.Enum):
    PERMIT = "permis"
    QUOTE = "devis"
    INVOICE = "facture"
    CONTRACT = "contrat"
    RECEIVING = "reception"
    OTHER = "autre"


class EquipmentStatus(str, enum.Enum):
    INSTALLED = "installe"
    UNDER_MAINTENANCE = "en_maintenance"
    BROKEN = "en_panne"
    REPLACED = "remplace"
    DECOMMISSIONED = "decommissionne"


class ExpenseImputation(str, enum.Enum):
    OWNER = "proprietaire"
    TENANT = "locataire"
    COPROPERTY = "copropriete"


# ---------------------------------------------------------------------------
# Prestataires
# ---------------------------------------------------------------------------
class ServiceProvider(Base):
    __tablename__ = "service_providers"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    company_name = Column(String(255), nullable=False)
    contact_name = Column(String(255))
    email = Column(String(255))
    phone = Column(String(30))
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    siret = Column(String(14))
    specialties = Column(JSON, default=list)   # plomberie, electricite, ...
    intervention_zone = Column(String(255))
    tariff_hourly = Column(Float)
    tariff_description = Column(Text)
    insurance_reference = Column(String(255))
    insurance_expiry = Column(Date)
    certifications = Column(JSON, default=list)
    rating = Column(Float, default=0)
    rating_count = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    quotes = relationship("ProviderQuote", back_populates="provider", cascade="all, delete-orphan")
    evaluations = relationship("ProviderEvaluation", back_populates="provider", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Ticketing / demandes d'intervention
# ---------------------------------------------------------------------------
class MaintenanceTicket(Base):
    __tablename__ = "maintenance_tickets"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    source = Column(Enum(TicketSource), default=TicketSource.MANAGER, nullable=False)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, index=True)
    owner_id = Column(Integer, ForeignKey("owners.id", ondelete="SET NULL"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="SET NULL"), nullable=True, index=True)
    category = Column(Enum(TicketCategory), default=TicketCategory.AUTRE, nullable=False, index=True)
    urgency = Column(Enum(TicketUrgency), default=TicketUrgency.MEDIUM, nullable=False, index=True)
    status = Column(Enum(TicketStatus), default=TicketStatus.NEW, nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    location = Column(String(255))        # Pièce / localisation dans le bien
    sla_deadline = Column(DateTime(timezone=True))
    escalated = Column(Boolean, default=False)
    assigned_to = Column(String(255))
    provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="SET NULL"), nullable=True)
    estimated_cost = Column(Float, default=0)
    final_cost = Column(Float, default=0)
    reported_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    resolved_at = Column(DateTime(timezone=True))
    closed_at = Column(DateTime(timezone=True))
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    tenant = relationship("Tenant")
    owner = relationship("Owner")
    lease = relationship("Lease")
    provider = relationship("ServiceProvider")
    attachments = relationship("TicketAttachment", back_populates="ticket", cascade="all, delete-orphan")
    status_history = relationship("TicketStatusHistory", back_populates="ticket", cascade="all, delete-orphan")
    quotes = relationship("ProviderQuote", back_populates="ticket", cascade="all, delete-orphan")
    evaluations = relationship("ProviderEvaluation", back_populates="ticket", cascade="all, delete-orphan")


class TicketAttachment(Base):
    __tablename__ = "ticket_attachments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(255))
    storage_path = Column(String(700), nullable=False)
    mime_type = Column(String(100))
    file_size = Column(Integer)
    caption = Column(String(500))
    captured_at = Column(DateTime(timezone=True))
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("MaintenanceTicket", back_populates="attachments")


class TicketStatusHistory(Base):
    __tablename__ = "ticket_status_history"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    from_status = Column(Enum(TicketStatus))
    to_status = Column(Enum(TicketStatus), nullable=False)
    note = Column(Text)
    changed_by = Column(String(255))
    changed_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("MaintenanceTicket", back_populates="status_history")


class ProviderQuote(Base):
    __tablename__ = "provider_quotes"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    amount = Column(Float, nullable=False)
    description = Column(Text)
    valid_until = Column(Date)
    status = Column(Enum(QuoteStatus), default=QuoteStatus.PENDING, nullable=False)
    attachment_url = Column(String(700))
    received_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("MaintenanceTicket", back_populates="quotes")
    provider = relationship("ServiceProvider", back_populates="quotes")


class ProviderEvaluation(Base):
    __tablename__ = "provider_evaluations"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False)  # 1..5
    comment = Column(Text)
    would_reuse = Column(Boolean, default=True)
    evaluated_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ticket = relationship("MaintenanceTicket", back_populates="evaluations")
    provider = relationship("ServiceProvider", back_populates="evaluations")


# ---------------------------------------------------------------------------
# Maintenance préventive
# ---------------------------------------------------------------------------
class PreventiveMaintenancePlan(Base):
    """Planification récurrente d'une maintenance préventive."""
    __tablename__ = "preventive_maintenance_plans"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    maintenance_type = Column(Enum(MaintenanceType), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    interval_months = Column(Integer, default=12, nullable=False)
    frequency_label = Column(String(100), default="Annuel")
    next_due_date = Column(Date, nullable=False, index=True)
    status = Column(Enum(MaintenancePlanStatus), default=MaintenancePlanStatus.ACTIVE, nullable=False)
    assigned_provider_id = Column(Integer, ForeignKey("service_providers.id", ondelete="SET NULL"))
    estimated_cost = Column(Float, default=0)
    last_completed_at = Column(DateTime(timezone=True))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    assigned_provider = relationship("ServiceProvider")
    tasks = relationship("PreventiveMaintenanceTask", back_populates="plan", cascade="all, delete-orphan")


class PreventiveMaintenanceTask(Base):
    """Exécution concrète d'une maintenance préventive (planification + suivi)."""
    __tablename__ = "preventive_maintenance_tasks"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    plan_id = Column(Integer, ForeignKey("preventive_maintenance_plans.id", ondelete="CASCADE"), nullable=False, index=True)
    scheduled_date = Column(Date, nullable=False)
    status = Column(String(30), default="scheduled", index=True)  # scheduled, done, overdue, cancelled
    completed_at = Column(DateTime(timezone=True))
    cost = Column(Float, default=0)
    performed_by = Column(String(255))
    observations = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    plan = relationship("PreventiveMaintenancePlan", back_populates="tasks")


# ---------------------------------------------------------------------------
# Travaux lourds
# ---------------------------------------------------------------------------
class WorkProject(Base):
    __tablename__ = "work_projects"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    project_type = Column(String(100))
    status = Column(Enum(WorkProjectStatus), default=WorkProjectStatus.DRAFT, nullable=False, index=True)
    budget = Column(Float, default=0)
    actual_cost = Column(Float, default=0)
    start_date = Column(Date)
    end_date = Column(Date)
    progress = Column(Float, default=0)  # 0..100
    responsible = Column(String(255))
    notes = Column(Text)
    created_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    phases = relationship("WorkPhase", back_populates="project", cascade="all, delete-orphan")
    documents = relationship("WorkDocument", back_populates="project", cascade="all, delete-orphan")


class WorkPhase(Base):
    __tablename__ = "work_phases"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("work_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    start_date = Column(Date)
    end_date = Column(Date)
    progress = Column(Float, default=0)
    display_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("WorkProject", back_populates="phases")


class WorkDocument(Base):
    __tablename__ = "work_documents"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("work_projects.id", ondelete="CASCADE"), nullable=False, index=True)
    document_type = Column(Enum(WorkDocumentType), default=WorkDocumentType.OTHER, nullable=False)
    title = Column(String(255), nullable=False)
    original_filename = Column(String(255))
    storage_path = Column(String(700), nullable=False)
    mime_type = Column(String(100))
    file_size = Column(Integer)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    project = relationship("WorkProject", back_populates="documents")


# ---------------------------------------------------------------------------
# Inventaire des équipements
# ---------------------------------------------------------------------------
class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    category = Column(String(100))
    brand = Column(String(150))
    model = Column(String(150))
    serial_number = Column(String(150))
    location = Column(String(255))
    installation_date = Column(Date)
    warranty_until = Column(Date)
    maintenance_contract = Column(String(255))
    replacement_date = Column(Date)          # Date de remplacement prévisionnelle
    status = Column(Enum(EquipmentStatus), default=EquipmentStatus.INSTALLED, nullable=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = relationship("Property")
    logs = relationship("EquipmentLog", back_populates="equipment", cascade="all, delete-orphan")


class EquipmentLog(Base):
    """Historique des pannes / interventions sur un équipement."""
    __tablename__ = "equipment_logs"

    id = Column(Integer, primary_key=True, index=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id", ondelete="SET NULL"), nullable=True)
    log_type = Column(String(50), default="maintenance")  # panne, maintenance, replacement
    description = Column(Text)
    cost = Column(Float, default=0)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now())

    equipment = relationship("Equipment", back_populates="logs")
    ticket = relationship("MaintenanceTicket")


# ---------------------------------------------------------------------------
# Suivi financier maintenance
# ---------------------------------------------------------------------------
class MaintenanceExpense(Base):
    __tablename__ = "maintenance_expenses"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    ticket_id = Column(Integer, ForeignKey("maintenance_tickets.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("work_projects.id", ondelete="SET NULL"), nullable=True)
    amount = Column(Float, nullable=False)
    vat_rate = Column(Float, default=0)
    expense_date = Column(Date, nullable=False)
    imputation = Column(Enum(ExpenseImputation), default=ExpenseImputation.OWNER, nullable=False)
    cost_type = Column(String(100))        # intervention, piece, main_oeuvre
    description = Column(Text)
    provider_name = Column(String(255))
    invoice_reference = Column(String(100))
    paid = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    property = relationship("Property")
    ticket = relationship("MaintenanceTicket")
    project = relationship("WorkProject")
