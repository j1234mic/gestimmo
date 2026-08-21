"""Modèles du module de gestion des locataires.

Le module conserve séparément le dossier de candidature (données fournies avant
validation) et la fiche locataire. Une candidature acceptée est convertie en
locataire par le service métier afin de garder une piste d'audit complète.
"""

import enum

from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship as orm_relationship
from sqlalchemy.sql import func

from app.database import Base


class TenantStatus(str, enum.Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    NOTICE = "notice"
    LEFT = "left"
    SUSPENDED = "suspended"


class EmploymentStatus(str, enum.Enum):
    EMPLOYEE = "employee"
    CIVIL_SERVANT = "civil_servant"
    SELF_EMPLOYED = "self_employed"
    STUDENT = "student"
    RETIRED = "retired"
    UNEMPLOYED = "unemployed"
    OTHER = "other"


class ContractType(str, enum.Enum):
    CDI = "cdi"
    CDD = "cdd"
    TEMPORARY = "temporary"
    APPRENTICESHIP = "apprenticeship"
    FREELANCE = "freelance"
    PUBLIC_SERVICE = "public_service"
    NONE = "none"
    OTHER = "other"


class IncomeType(str, enum.Enum):
    SALARY = "salary"
    PENSION = "pension"
    BENEFIT = "benefit"
    RENTAL = "rental"
    BUSINESS = "business"
    SCHOLARSHIP = "scholarship"
    OTHER = "other"


class ApplicationStatus(str, enum.Enum):
    DRAFT = "draft"
    PENDING = "pending"
    ACCEPTED = "accepted"
    REFUSED = "refused"
    WITHDRAWN = "withdrawn"


class DocumentType(str, enum.Enum):
    IDENTITY = "identity"
    PAY_SLIP = "pay_slip"
    TAX_NOTICE = "tax_notice"
    PROOF_OF_ADDRESS = "proof_of_address"
    EMPLOYMENT_CONTRACT = "employment_contract"
    EMPLOYER_CERTIFICATE = "employer_certificate"
    GUARANTEE_DEED = "guarantee_deed"
    VISALE_CERTIFICATE = "visale_certificate"
    GLI_CERTIFICATE = "gli_certificate"
    LEASE = "lease"
    OTHER = "other"


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"


class GuarantorType(str, enum.Enum):
    INDIVIDUAL = "individual"
    COMPANY = "company"


class SuretyType(str, enum.Enum):
    SIMPLE = "simple"
    SOLIDARY = "solidary"


class GuaranteeScheme(str, enum.Enum):
    PERSONAL = "personal"
    VISALE = "visale"
    GLI = "gli"
    OTHER = "other"


class LeaseStatus(str, enum.Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    TERMINATED = "terminated"
    EXPIRED = "expired"


class PaymentStatus(str, enum.Enum):
    DUE = "due"
    PARTIAL = "partial"
    PAID = "paid"
    OVERDUE = "overdue"
    CANCELLED = "cancelled"


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    CLOSED = "closed"


class IncidentPriority(str, enum.Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class LegalCaseStatus(str, enum.Enum):
    OPEN = "open"
    MEDIATION = "mediation"
    LITIGATION = "litigation"
    PAYMENT_PLAN = "payment_plan"
    CLOSED = "closed"


class RentalApplication(Base):
    __tablename__ = "rental_applications"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(24), unique=True, nullable=False, index=True)
    tracking_token_hash = Column(String(64), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="SET NULL"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True, unique=True)
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.PENDING, nullable=False, index=True)

    # Informations personnelles et coordonnées
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    birth_date = Column(Date)
    birth_place = Column(String(200))
    nationality = Column(String(100), default="Française")
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(30), nullable=False)
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="France")

    # Situation professionnelle et revenus déclarés
    employment_status = Column(Enum(EmploymentStatus), nullable=False)
    occupation = Column(String(200))
    employer_name = Column(String(255))
    employer_address = Column(String(500))
    contract_type = Column(Enum(ContractType))
    employment_start_date = Column(Date)
    trial_period_end = Column(Date)
    monthly_net_income = Column(Float, default=0, nullable=False)
    other_monthly_income = Column(Float, default=0, nullable=False)
    current_monthly_rent = Column(Float)

    desired_move_in_date = Column(Date)
    occupants_count = Column(Integer, default=1)
    notes = Column(Text)
    privacy_consent = Column(Boolean, default=False, nullable=False)

    # Résultat du moteur de scoring
    solvency_score = Column(Float, default=0, nullable=False)
    score_breakdown = Column(JSON, default=dict)
    risk_level = Column(String(20), default="unscored")
    scored_at = Column(DateTime(timezone=True))

    rejection_reason = Column(Text)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now())
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    property = orm_relationship("Property")
    tenant = orm_relationship("Tenant", back_populates="application", foreign_keys=[tenant_id])
    documents = orm_relationship("TenantDocument", back_populates="application", cascade="all, delete-orphan")
    guarantors = orm_relationship("Guarantor", back_populates="application", cascade="all, delete-orphan")
    status_history = orm_relationship(
        "ApplicationStatusHistory", back_populates="application", cascade="all, delete-orphan",
        order_by="ApplicationStatusHistory.created_at",
    )
    notifications = orm_relationship("TenantNotification", back_populates="application")


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(24), unique=True, nullable=False, index=True)
    status = Column(Enum(TenantStatus), default=TenantStatus.ACTIVE, nullable=False, index=True)

    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    birth_date = Column(Date)
    birth_place = Column(String(200))
    nationality = Column(String(100), default="Française")
    email = Column(String(255), nullable=False, index=True)
    phone = Column(String(30))
    mobile = Column(String(30))
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="France")

    employment_status = Column(Enum(EmploymentStatus))
    occupation = Column(String(200))
    employer_name = Column(String(255))
    employer_address = Column(String(500))
    contract_type = Column(Enum(ContractType))
    employment_start_date = Column(Date)
    trial_period_end = Column(Date)
    monthly_net_income = Column(Float, default=0)
    other_monthly_income = Column(Float, default=0)

    solvency_score = Column(Float, default=0, nullable=False)
    reliability_score = Column(Float, default=100, nullable=False)
    score_breakdown = Column(JSON, default=dict)
    score_updated_at = Column(DateTime(timezone=True))

    portal_password_hash = Column(String(255))
    portal_enabled = Column(Boolean, default=False, nullable=False)
    last_portal_login_at = Column(DateTime(timezone=True))

    notes = Column(Text)
    tags = Column(JSON, default=list)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    application = orm_relationship("RentalApplication", back_populates="tenant", uselist=False, foreign_keys="RentalApplication.tenant_id")
    incomes = orm_relationship("TenantIncome", back_populates="tenant", cascade="all, delete-orphan")
    emergency_contacts = orm_relationship("EmergencyContact", back_populates="tenant", cascade="all, delete-orphan")
    rental_history = orm_relationship("RentalHistory", back_populates="tenant", cascade="all, delete-orphan")
    guarantors = orm_relationship("Guarantor", back_populates="tenant", cascade="all, delete-orphan")
    documents = orm_relationship("TenantDocument", back_populates="tenant")
    leases = orm_relationship("Lease", back_populates="tenant", cascade="all, delete-orphan")
    payments = orm_relationship("RentPayment", back_populates="tenant", cascade="all, delete-orphan")
    incidents = orm_relationship("TenantIncident", back_populates="tenant", cascade="all, delete-orphan")
    messages = orm_relationship("TenantMessage", back_populates="tenant", cascade="all, delete-orphan")
    interactions = orm_relationship("TenantInteraction", back_populates="tenant", cascade="all, delete-orphan")
    legal_cases = orm_relationship("LegalCase", back_populates="tenant", cascade="all, delete-orphan")
    notifications = orm_relationship("TenantNotification", back_populates="tenant", cascade="all, delete-orphan")
    alerts = orm_relationship("TenantAlert", back_populates="tenant", cascade="all, delete-orphan")


class TenantIncome(Base):
    __tablename__ = "tenant_incomes"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    income_type = Column(Enum(IncomeType), nullable=False)
    label = Column(String(200))
    monthly_amount = Column(Float, nullable=False)
    payer = Column(String(255))
    start_date = Column(Date)
    end_date = Column(Date)
    is_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = orm_relationship("Tenant", back_populates="incomes")


class EmergencyContact(Base):
    __tablename__ = "tenant_emergency_contacts"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    relationship = Column(String(100))
    phone = Column(String(30), nullable=False)
    email = Column(String(255))
    is_primary = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = orm_relationship("Tenant", back_populates="emergency_contacts")


class RentalHistory(Base):
    __tablename__ = "tenant_rental_history"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    address = Column(String(500), nullable=False)
    city = Column(String(100))
    landlord_name = Column(String(255))
    landlord_phone = Column(String(30))
    start_date = Column(Date)
    end_date = Column(Date)
    monthly_rent = Column(Float)
    departure_reason = Column(Text)
    payment_incidents = Column(Boolean, default=False)
    reference_checked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = orm_relationship("Tenant", back_populates="rental_history")


class Guarantor(Base):
    __tablename__ = "guarantors"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("rental_applications.id", ondelete="CASCADE"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    guarantor_type = Column(Enum(GuarantorType), default=GuarantorType.INDIVIDUAL, nullable=False)
    company_name = Column(String(255))
    first_name = Column(String(100))
    last_name = Column(String(100))
    birth_date = Column(Date)
    birth_place = Column(String(200))
    nationality = Column(String(100), default="Française")
    email = Column(String(255))
    phone = Column(String(30))
    address = Column(String(500))
    postal_code = Column(String(10))
    city = Column(String(100))
    country = Column(String(100), default="France")

    employment_status = Column(Enum(EmploymentStatus))
    occupation = Column(String(200))
    employer_name = Column(String(255))
    contract_type = Column(Enum(ContractType))
    employment_start_date = Column(Date)
    monthly_net_income = Column(Float, default=0)
    other_monthly_income = Column(Float, default=0)

    surety_type = Column(Enum(SuretyType), default=SuretyType.SOLIDARY)
    guarantee_scheme = Column(Enum(GuaranteeScheme), default=GuaranteeScheme.PERSONAL)
    guarantee_reference = Column(String(100))
    guaranteed_amount = Column(Float)
    guarantee_start_date = Column(Date)
    guarantee_end_date = Column(Date)
    deed_signed_at = Column(DateTime(timezone=True))
    is_verified = Column(Boolean, default=False)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    application = orm_relationship("RentalApplication", back_populates="guarantors")
    tenant = orm_relationship("Tenant", back_populates="guarantors")
    documents = orm_relationship("TenantDocument", back_populates="guarantor")


class TenantDocument(Base):
    __tablename__ = "tenant_documents"

    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("rental_applications.id", ondelete="CASCADE"), nullable=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    guarantor_id = Column(Integer, ForeignKey("guarantors.id", ondelete="CASCADE"), nullable=True, index=True)
    document_type = Column(Enum(DocumentType), nullable=False, index=True)
    pay_slip_period = Column(String(7))
    original_filename = Column(String(255), nullable=False)
    storage_path = Column(String(700), nullable=False)
    url = Column(String(700), nullable=False)
    mime_type = Column(String(100))
    file_size = Column(Integer)
    file_hash = Column(String(64), index=True)

    verification_status = Column(Enum(VerificationStatus), default=VerificationStatus.PENDING, nullable=False)
    ocr_text = Column(Text)
    ocr_confidence = Column(Float, default=0)
    verification_checks = Column(JSON, default=dict)
    verified_at = Column(DateTime(timezone=True))
    verified_by = Column(String(255))
    rejection_reason = Column(Text)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())

    application = orm_relationship("RentalApplication", back_populates="documents")
    tenant = orm_relationship("Tenant", back_populates="documents")
    guarantor = orm_relationship("Guarantor", back_populates="documents")


class ApplicationStatusHistory(Base):
    __tablename__ = "application_status_history"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("rental_applications.id", ondelete="CASCADE"), nullable=False, index=True)
    previous_status = Column(Enum(ApplicationStatus))
    new_status = Column(Enum(ApplicationStatus), nullable=False)
    reason = Column(Text)
    changed_by = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    application = orm_relationship("RentalApplication", back_populates="status_history")


class Lease(Base):
    __tablename__ = "tenant_leases"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="RESTRICT"), nullable=False, index=True)
    status = Column(Enum(LeaseStatus), default=LeaseStatus.DRAFT, nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date)
    monthly_rent = Column(Float, nullable=False)
    monthly_charges = Column(Float, default=0)
    deposit = Column(Float, default=0)
    payment_day = Column(Integer, default=5)
    lease_type = Column(String(50), default="unfurnished")
    signed_at = Column(DateTime(timezone=True))
    document_url = Column(String(700))
    document_storage_path = Column(String(700))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = orm_relationship("Tenant", back_populates="leases")
    property = orm_relationship("Property")
    payments = orm_relationship("RentPayment", back_populates="lease", cascade="all, delete-orphan")


class RentPayment(Base):
    __tablename__ = "rent_payments"
    __table_args__ = (UniqueConstraint("lease_id", "period", name="uq_rent_payment_lease_period"),)

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False, index=True)
    period = Column(String(7), nullable=False)  # YYYY-MM
    due_date = Column(Date, nullable=False, index=True)
    amount_due = Column(Float, nullable=False)
    amount_paid = Column(Float, default=0, nullable=False)
    status = Column(Enum(PaymentStatus), default=PaymentStatus.DUE, nullable=False, index=True)
    paid_at = Column(DateTime(timezone=True))
    payment_method = Column(String(50))
    external_reference = Column(String(255))
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = orm_relationship("Tenant", back_populates="payments")
    lease = orm_relationship("Lease", back_populates="payments")
    receipt = orm_relationship("RentReceipt", back_populates="payment", uselist=False, cascade="all, delete-orphan")
    attempts = orm_relationship("PaymentAttempt", back_populates="payment", cascade="all, delete-orphan")


class RentReceipt(Base):
    __tablename__ = "rent_receipts"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    payment_id = Column(Integer, ForeignKey("rent_payments.id", ondelete="CASCADE"), nullable=False, unique=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(7), nullable=False)
    issued_at = Column(DateTime(timezone=True), server_default=func.now())
    file_url = Column(String(700))

    payment = orm_relationship("RentPayment", back_populates="receipt")
    tenant = orm_relationship("Tenant")
    lease = orm_relationship("Lease")


class PaymentAttempt(Base):
    __tablename__ = "tenant_payment_attempts"

    id = Column(Integer, primary_key=True)
    payment_id = Column(Integer, ForeignKey("rent_payments.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(30), nullable=False)
    provider_session_id = Column(String(255), unique=True, index=True)
    amount = Column(Float, nullable=False)
    status = Column(String(30), default="created", nullable=False)
    checkout_url = Column(String(1000))
    failure_reason = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True))

    payment = orm_relationship("RentPayment", back_populates="attempts")


class TenantIncident(Base):
    __tablename__ = "tenant_incidents"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="SET NULL"), nullable=True)
    category = Column(String(100), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=False)
    priority = Column(Enum(IncidentPriority), default=IncidentPriority.NORMAL, nullable=False)
    status = Column(Enum(IncidentStatus), default=IncidentStatus.OPEN, nullable=False, index=True)
    attachment_url = Column(String(700))
    assigned_to = Column(String(255))
    resolution = Column(Text)
    reported_at = Column(DateTime(timezone=True), server_default=func.now())
    resolved_at = Column(DateTime(timezone=True))
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = orm_relationship("Tenant", back_populates="incidents")
    lease = orm_relationship("Lease")


class TenantMessage(Base):
    __tablename__ = "tenant_messages"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_type = Column(String(20), nullable=False)  # tenant / manager
    sender_name = Column(String(255))
    subject = Column(String(255))
    content = Column(Text, nullable=False)
    attachment_url = Column(String(700))
    is_read = Column(Boolean, default=False, nullable=False)
    read_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = orm_relationship("Tenant", back_populates="messages")


class TenantInteraction(Base):
    __tablename__ = "tenant_interactions"

    id = Column(Integer, primary_key=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    interaction_type = Column(String(50), nullable=False)
    direction = Column(String(20), default="internal")
    subject = Column(String(255))
    content = Column(Text, nullable=False)
    actor = Column(String(255))
    related_entity_type = Column(String(50))
    related_entity_id = Column(Integer)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    tenant = orm_relationship("Tenant", back_populates="interactions")


class LegalCase(Base):
    __tablename__ = "tenant_legal_cases"

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(30), unique=True, nullable=False, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    lease_id = Column(Integer, ForeignKey("tenant_leases.id", ondelete="SET NULL"), nullable=True)
    status = Column(Enum(LegalCaseStatus), default=LegalCaseStatus.OPEN, nullable=False)
    case_type = Column(String(100), nullable=False)
    opened_at = Column(Date, nullable=False)
    closed_at = Column(Date)
    outstanding_amount = Column(Float, default=0)
    court_reference = Column(String(100))
    lawyer_name = Column(String(255))
    next_action_date = Column(Date)
    description = Column(Text)
    resolution = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    tenant = orm_relationship("Tenant", back_populates="legal_cases")
    lease = orm_relationship("Lease")


class TenantNotification(Base):
    __tablename__ = "tenant_notifications"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True, index=True)
    application_id = Column(Integer, ForeignKey("rental_applications.id", ondelete="SET NULL"), nullable=True, index=True)
    channel = Column(String(20), default="in_app")
    notification_type = Column(String(50), default="info")
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    delivery_status = Column(String(20), default="delivered")
    is_read = Column(Boolean, default=False)
    sent_at = Column(DateTime(timezone=True), server_default=func.now())
    read_at = Column(DateTime(timezone=True))

    tenant = orm_relationship("Tenant", back_populates="notifications")
    application = orm_relationship("RentalApplication", back_populates="notifications")


class TenantAlert(Base):
    __tablename__ = "tenant_alerts"
    __table_args__ = (UniqueConstraint("alert_type", "related_entity_id", name="uq_tenant_alert_entity"),)

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    alert_type = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), default="warning")
    title = Column(String(255), nullable=False)
    content = Column(Text)
    related_entity_id = Column(Integer)
    is_active = Column(Boolean, default=True, nullable=False)
    acknowledged_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    tenant = orm_relationship("Tenant", back_populates="alerts")
